"""Syntax-error handling, empty files, unicode-safe slicing, and
deterministic repeated parsing (same file -> same IDs, same structure)."""

from pathlib import Path

from app.domain.code_symbols.enums import ParseErrorType
from app.parsing.python.parser import PythonParser
from app.parsing.registry import build_default_registry, parse_source_bytes


def test_syntax_error_is_recorded_but_does_not_raise(python_parser: PythonParser) -> None:
    source = "def broken(:\n    pass\n\ndef good():\n    return 1\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert len(parsed.parse_errors) >= 1
    assert parsed.parse_errors[0].error_type is ParseErrorType.SYNTAX_ERROR
    assert parsed.parse_errors[0].recoverable is True


def test_syntax_error_does_not_discard_extractable_symbols(python_parser: PythonParser) -> None:
    source = "def broken(:\n    pass\n\ndef good():\n    return 1\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    names = {f.name for f in parsed.functions}
    assert "good" in names
    assert "broken" in names


def test_syntax_error_location_has_no_host_path_leak(python_parser: PythonParser) -> None:
    source = "def broken(:\n    pass\n"

    parsed = python_parser.parse(source, Path("app/mod.py"), "repo-1")

    for error in parsed.parse_errors:
        assert error.file_path == "app/mod.py"
        assert ":\\" not in error.file_path
        assert not error.file_path.startswith("/")


def test_empty_file_produces_valid_parsed_file(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("", Path("empty.py"), "repo-1")

    assert parsed.functions == []
    assert parsed.classes == []
    assert parsed.imports == []
    assert parsed.parse_errors == []
    assert parsed.module_docstring is None


def test_encoding_error_produces_controlled_error_not_an_exception() -> None:
    registry = build_default_registry()
    invalid_utf8_bytes = b"\xff\xfe\x00\x00garbage"

    parsed = parse_source_bytes(registry, invalid_utf8_bytes, Path("bad.py"), "repo-1")

    assert parsed is not None
    assert parsed.parse_errors[0].error_type is ParseErrorType.ENCODING_ERROR


def test_repeated_parsing_is_deterministic(python_parser: PythonParser) -> None:
    source = (
        "class AuthService(Base):\n"
        "    def login(self, username, password='x'):\n"
        "        auth.check()\n"
        "        return True\n"
    )

    first = python_parser.parse(source, Path("app/auth.py"), "repo-1")
    second = python_parser.parse(source, Path("app/auth.py"), "repo-1")

    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert [c.id for c in first.classes] == [c.id for c in second.classes]
    assert [m.id for m in first.classes[0].methods] == [m.id for m in second.classes[0].methods]
    assert [p.id for p in first.classes[0].methods[0].parameters] == [
        p.id for p in second.classes[0].methods[0].parameters
    ]
    assert [call.id for call in first.classes[0].methods[0].calls] == [
        call.id for call in second.classes[0].methods[0].calls
    ]


def test_unicode_identifiers_and_strings_are_sliced_correctly(python_parser: PythonParser) -> None:
    source = (
        "def café(名前: str) -> str:\n"
        '    """café docstring 名前."""\n'
        '    naïve_greeting = "héllo, " + 名前\n'
        "    return naïve_greeting\n"
    )

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    func = parsed.functions[0]

    assert func.name == "café"
    assert func.parameters[0].name == "名前"
    assert func.parameters[0].annotation == "str"
    assert func.docstring == "café docstring 名前."
    assert func.source_code == source.strip()


def test_unicode_before_a_node_does_not_corrupt_later_byte_offsets(
    python_parser: PythonParser,
) -> None:
    # A multi-byte character earlier in the file shifts byte offsets ahead
    # of it; if slicing used character offsets against byte positions (or
    # vice versa) this second function's text would be corrupted/misaligned.
    source = 'GREETING = "héllo wörld with ünïcödé"\n\n\ndef second():\n    return 2\n'

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].name == "second"
    assert parsed.functions[0].source_code == "def second():\n    return 2"
    assert parsed.functions[0].location.start_line == 4

"""Parser selection: registry behavior — see AGENTS.md rule 10."""

from pathlib import Path

import pytest

from app.parsing.base import LanguageParser
from app.parsing.exceptions import DuplicateParserRegistrationError
from app.parsing.python.parser import PythonParser
from app.parsing.registry import ParserRegistry, build_default_registry, parse_source_bytes


class _FakeJavaScriptParser:
    """A stand-in for a future non-Python parser (see AGENTS.md rule 10:
    "Support future JavaScript or Java parsers without modifying calling
    code")."""

    language = "javascript"

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix == ".js"

    def parse(self, source: str, file_path: Path, repository_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


def test_default_registry_selects_python_parser_for_py_files() -> None:
    registry = build_default_registry()

    parser = registry.get_parser_for_file(Path("app/main.py"))

    assert parser is not None
    assert parser.language == "python"


def test_registry_returns_none_for_unsupported_file() -> None:
    registry = build_default_registry()

    assert registry.get_parser_for_file(Path("README.md")) is None
    assert registry.get_parser_for_file(Path("script.sh")) is None


def test_registry_prevents_duplicate_language_registration() -> None:
    registry = ParserRegistry()
    registry.register(PythonParser())

    with pytest.raises(DuplicateParserRegistrationError):
        registry.register(PythonParser())


def test_registry_supports_multiple_languages_without_caller_changes() -> None:
    registry = ParserRegistry()
    registry.register(PythonParser())
    registry.register(_FakeJavaScriptParser())  # type: ignore[arg-type]

    assert registry.get_parser_for_file(Path("a.py")).language == "python"  # type: ignore[union-attr]
    assert registry.get_parser_for_file(Path("a.js")).language == "javascript"  # type: ignore[union-attr]
    assert set(registry.languages) == {"python", "javascript"}


def test_python_parser_satisfies_language_parser_protocol() -> None:
    assert isinstance(PythonParser(), LanguageParser)


def test_parse_source_bytes_returns_none_for_unsupported_extension() -> None:
    registry = build_default_registry()

    result = parse_source_bytes(registry, b"irrelevant", Path("notes.txt"), "repo-1")

    assert result is None


def test_parse_source_bytes_reports_encoding_error_without_raising() -> None:
    registry = build_default_registry()
    invalid_utf8 = b"\xff\xfe\x00bad"

    parsed = parse_source_bytes(registry, invalid_utf8, Path("bad.py"), "repo-1")

    assert parsed is not None
    assert len(parsed.parse_errors) == 1
    assert parsed.parse_errors[0].error_type.value == "encoding_error"
    assert parsed.parse_errors[0].recoverable is False


def test_parse_source_bytes_parses_valid_utf8_python() -> None:
    registry = build_default_registry()

    parsed = parse_source_bytes(registry, b"def f():\n    return 1\n", Path("m.py"), "repo-1")

    assert parsed is not None
    assert [f.name for f in parsed.functions] == ["f"]

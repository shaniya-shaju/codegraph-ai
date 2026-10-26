"""Function extraction: signature, docstring, source text, async, line numbers,
complexity signals."""

from pathlib import Path

from app.parsing.python.parser import PythonParser


def test_function_extraction_basic_fields(python_parser: PythonParser) -> None:
    source = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'

    parsed = python_parser.parse(source, Path("math_utils.py"), "repo-1")

    assert len(parsed.functions) == 1
    func = parsed.functions[0]
    assert func.name == "add"
    assert func.qualified_name == "math_utils.add"
    assert func.docstring == "Add two numbers."
    assert func.async_function is False
    assert func.parent_class is None


def test_function_one_based_line_numbers(python_parser: PythonParser) -> None:
    source = "x = 1\n\n\ndef add(a, b):\n    return a + b\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    func = parsed.functions[0]
    # `def` is on line 4 (1-based): two blank lines follow `x = 1` on line 1.
    assert func.location.start_line == 4
    assert func.location.end_line == 5


def test_async_function_is_flagged(python_parser: PythonParser) -> None:
    source = "async def fetch():\n    return 1\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].async_function is True


def test_function_source_code_is_preserved_exactly(python_parser: PythonParser) -> None:
    source = "def add(a, b):\n    total = a + b\n    return total\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].source_code == source.strip()


def test_function_signature_excludes_body(python_parser: PythonParser) -> None:
    source = "def add(a: int, b: int = 1) -> int:\n    return a + b\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].signature == "def add(a: int, b: int = 1) -> int:"


def test_function_return_annotation(python_parser: PythonParser) -> None:
    source = "def add(a, b) -> int:\n    return a + b\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].return_annotation == "int"


def test_function_without_docstring_is_none(python_parser: PythonParser) -> None:
    source = "def add(a, b):\n    return a + b\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].docstring is None


def test_complexity_signals_counts(python_parser: PythonParser) -> None:
    source = (
        "def f(a):\n"
        "    if a:\n"
        "        pass\n"
        "    for x in range(a):\n"
        "        while x:\n"
        "            break\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        pass\n"
        "    except TypeError:\n"
        "        pass\n"
        "    if a:\n"
        "        return 1\n"
        "    return 2\n"
    )

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    signals = parsed.functions[0].complexity_signals

    assert signals.branch_count == 2
    assert signals.loop_count == 2
    assert signals.exception_handler_count == 2
    assert signals.return_count == 2


def test_complexity_signals_do_not_double_count_nested_function(
    python_parser: PythonParser,
) -> None:
    source = (
        "def outer():\n"
        "    if True:\n"
        "        pass\n"
        "\n"
        "    def inner():\n"
        "        if True:\n"
        "            pass\n"
        "        if True:\n"
        "            pass\n"
        "\n"
        "    return inner\n"
    )

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    outer = next(f for f in parsed.functions if f.name == "outer")
    inner = next(f for f in parsed.functions if f.name == "inner")

    assert outer.complexity_signals.branch_count == 1
    assert outer.complexity_signals.nested_function_count == 1
    assert inner.complexity_signals.branch_count == 2


def test_await_count(python_parser: PythonParser) -> None:
    source = "async def f():\n    await a()\n    await b()\n    return 1\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].complexity_signals.await_count == 2

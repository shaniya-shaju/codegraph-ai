"""Parameter extraction: kinds, annotations, defaults, position."""

from pathlib import Path

from app.domain.code_symbols.enums import ParameterKind
from app.parsing.python.parser import PythonParser


def test_positional_only_and_regular_parameters(python_parser: PythonParser) -> None:
    source = "def divide(numerator, denominator, /, precision=2):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    params = {p.name: p for p in parsed.functions[0].parameters}

    assert params["numerator"].kind is ParameterKind.POSITIONAL_ONLY
    assert params["denominator"].kind is ParameterKind.POSITIONAL_ONLY
    assert params["precision"].kind is ParameterKind.POSITIONAL
    assert params["precision"].default_value == "2"


def test_keyword_only_parameters_after_bare_star(python_parser: PythonParser) -> None:
    source = "def configure(*, debug=False, level='info'):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    params = {p.name: p for p in parsed.functions[0].parameters}

    assert params["debug"].kind is ParameterKind.KEYWORD_ONLY
    assert params["level"].kind is ParameterKind.KEYWORD_ONLY


def test_keyword_only_parameters_after_var_positional(python_parser: PythonParser) -> None:
    source = "def send(message, *args, retries=1):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    params = {p.name: p for p in parsed.functions[0].parameters}

    assert params["message"].kind is ParameterKind.POSITIONAL
    assert params["args"].kind is ParameterKind.VAR_POSITIONAL
    assert params["retries"].kind is ParameterKind.KEYWORD_ONLY


def test_variadic_star_args_and_kwargs(python_parser: PythonParser) -> None:
    source = "def f(*args, **kwargs):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    params = {p.name: p for p in parsed.functions[0].parameters}

    assert params["args"].kind is ParameterKind.VAR_POSITIONAL
    assert params["kwargs"].kind is ParameterKind.VAR_KEYWORD


def test_parameter_annotation_and_default(python_parser: PythonParser) -> None:
    source = "def compute(a: int, b: float, label: str = 'x') -> bool:\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    params = {p.name: p for p in parsed.functions[0].parameters}

    assert params["a"].annotation == "int"
    assert params["a"].default_value is None
    assert params["label"].annotation == "str"
    assert params["label"].default_value == "'x'"


def test_parameter_position_is_ordered(python_parser: PythonParser) -> None:
    source = "def f(a, b, c):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    positions = [p.position for p in parsed.functions[0].parameters]

    assert positions == [0, 1, 2]


def test_self_parameter_is_extracted_like_any_other(python_parser: PythonParser) -> None:
    source = "class C:\n    def method(self, x):\n        pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    params = parsed.classes[0].methods[0].parameters

    assert params[0].name == "self"
    assert params[0].kind is ParameterKind.POSITIONAL

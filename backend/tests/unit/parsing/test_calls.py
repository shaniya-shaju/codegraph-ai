"""Call-expression extraction and syntax-only classification.

See the parsing task: this never claims a call has been resolved to a
concrete symbol — only its syntactic shape is classified.
"""

from pathlib import Path

from app.domain.code_symbols.enums import CallType
from app.parsing.python.parser import PythonParser


def _calls_by_expression(python_parser: PythonParser, source: str) -> dict[str, object]:
    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    return {c.called_expression: c for c in parsed.functions[0].calls}


def test_direct_call(python_parser: PythonParser) -> None:
    calls = _calls_by_expression(python_parser, "def f():\n    login()\n")

    call = calls["login"]
    assert call.call_type is CallType.DIRECT
    assert call.probable_target_name == "login"


def test_attribute_call(python_parser: PythonParser) -> None:
    calls = _calls_by_expression(python_parser, "def f():\n    auth.login()\n")

    call = calls["auth.login"]
    assert call.call_type is CallType.ATTRIBUTE
    assert call.probable_target_name == "login"


def test_self_attribute_call(python_parser: PythonParser) -> None:
    source = "class C:\n    def f(self):\n        self.validate()\n"
    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    call = parsed.classes[0].methods[0].calls[0]

    assert call.called_expression == "self.validate"
    assert call.call_type is CallType.ATTRIBUTE
    assert call.probable_target_name == "validate"


def test_constructor_candidate_call(python_parser: PythonParser) -> None:
    calls = _calls_by_expression(python_parser, "def f():\n    UserService()\n")

    call = calls["UserService"]
    assert call.call_type is CallType.CONSTRUCTOR_CANDIDATE
    assert call.probable_target_name == "UserService"


def test_call_on_call_result_is_dynamic_or_unknown(python_parser: PythonParser) -> None:
    calls = _calls_by_expression(python_parser, "def f():\n    factory()()\n")

    outer_call = calls["factory()"]
    assert outer_call.call_type is CallType.DYNAMIC_OR_UNKNOWN
    assert outer_call.probable_target_name is None
    # the inner factory() call is itself a separate, ordinary direct call
    assert calls["factory"].call_type is CallType.DIRECT


def test_chained_attribute_call_rooted_in_identifier(python_parser: PythonParser) -> None:
    source = "class C:\n    def f(self):\n        self.repo.users.find()\n"
    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    call = parsed.classes[0].methods[0].calls[0]

    assert call.called_expression == "self.repo.users.find"
    assert call.call_type is CallType.ATTRIBUTE
    assert call.probable_target_name == "find"


def test_argument_count(python_parser: PythonParser) -> None:
    calls = _calls_by_expression(python_parser, "def f():\n    do_thing(1, 2, three=3)\n")

    assert calls["do_thing"].argument_count == 3


def test_call_caller_qualified_name(python_parser: PythonParser) -> None:
    source = "class AuthService:\n    def login(self):\n        auth.check()\n"
    parsed = python_parser.parse(source, Path("app/auth.py"), "repo-1")
    call = parsed.classes[0].methods[0].calls[0]

    assert call.caller_qualified_name == "app.auth.AuthService.login"


def test_call_location_is_one_based(python_parser: PythonParser) -> None:
    calls = _calls_by_expression(python_parser, "def f():\n    login()\n")

    assert calls["login"].location.start_line == 2

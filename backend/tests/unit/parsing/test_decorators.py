"""Decorator extraction and framework-agnostic API-route recognition."""

from pathlib import Path

from app.parsing.python.parser import PythonParser


def test_plain_decorator_raw_expression(python_parser: PythonParser) -> None:
    source = "class C:\n    @staticmethod\n    def build():\n        pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    method = parsed.classes[0].methods[0]

    assert len(method.decorators) == 1
    assert method.decorators[0].raw_expression == "@staticmethod"
    assert method.decorators[0].route_info is None


def test_multiple_decorators_preserve_order(python_parser: PythonParser) -> None:
    source = (
        "class C:\n    @classmethod\n    @some_other_decorator\n    def build(cls):\n        pass\n"
    )

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    decorators = [d.raw_expression for d in parsed.classes[0].methods[0].decorators]

    assert decorators == ["@classmethod", "@some_other_decorator"]


def test_fastapi_get_decorator_route_info(python_parser: PythonParser) -> None:
    source = '@app.get("/users")\ndef list_users():\n    return []\n'

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    decorator = parsed.functions[0].decorators[0]

    assert decorator.raw_expression == '@app.get("/users")'
    assert decorator.route_info is not None
    assert decorator.route_info.http_method == "GET"
    assert decorator.route_info.path == "/users"


def test_fastapi_post_decorator_route_info(python_parser: PythonParser) -> None:
    source = '@router.post("/login")\ndef login():\n    pass\n'

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    route = parsed.functions[0].decorators[0].route_info

    assert route.http_method == "POST"
    assert route.path == "/login"


def test_flask_blueprint_route_default_method_is_get(python_parser: PythonParser) -> None:
    source = '@blueprint.route("/health")\ndef health():\n    return "ok"\n'

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    route = parsed.functions[0].decorators[0].route_info

    assert route.http_method == "GET"
    assert route.path == "/health"


def test_flask_blueprint_route_with_explicit_methods(python_parser: PythonParser) -> None:
    source = '@blueprint.route("/login", methods=["POST"])\ndef login():\n    return "ok"\n'

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    route = parsed.functions[0].decorators[0].route_info

    assert route.http_method == "POST"
    assert route.path == "/login"


def test_non_route_decorator_call_has_no_route_info(python_parser: PythonParser) -> None:
    source = "@retry(times=3)\ndef flaky():\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions[0].decorators[0].route_info is None


def test_decorated_class(python_parser: PythonParser) -> None:
    source = "@dataclass\nclass Point:\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.classes[0].decorators[0].raw_expression == "@dataclass"

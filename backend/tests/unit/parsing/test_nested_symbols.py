"""Nested-function flattening and qualified-name construction — see the
parsing task's "Qualified-name rules" examples."""

from pathlib import Path

from app.parsing.python.parser import PythonParser


def test_nested_function_qualified_name_matches_spec_example(
    python_parser: PythonParser,
) -> None:
    source = (
        "def login():\n"
        "    def validate_password():\n"
        "        return True\n"
        "    return validate_password()\n"
    )

    parsed = python_parser.parse(source, Path("app/auth/service.py"), "repo-1")

    names = {f.qualified_name for f in parsed.functions}
    assert names == {
        "app.auth.service.login",
        "app.auth.service.login.validate_password",
    }


def test_method_qualified_name_matches_spec_example(python_parser: PythonParser) -> None:
    source = "class AuthService:\n    def login(self):\n        return True\n"

    parsed = python_parser.parse(source, Path("app/auth/service.py"), "repo-1")

    method = parsed.classes[0].methods[0]
    assert parsed.classes[0].qualified_name == "app.auth.service.AuthService"
    assert method.qualified_name == "app.auth.service.AuthService.login"


def test_nested_class_qualified_name_matches_spec_example(python_parser: PythonParser) -> None:
    source = "class AuthService:\n    class Config:\n        pass\n"

    parsed = python_parser.parse(source, Path("app/auth/service.py"), "repo-1")

    nested = parsed.classes[0].nested_classes[0]
    assert nested.qualified_name == "app.auth.service.AuthService.Config"


def test_function_nested_inside_a_method_flattens_to_file_level(
    python_parser: PythonParser,
) -> None:
    source = (
        "class C:\n"
        "    def method(self):\n"
        "        def helper():\n"
        "            return 1\n"
        "        return helper()\n"
    )

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert [f.name for f in parsed.functions] == ["helper"]
    assert parsed.functions[0].qualified_name == "m.C.method.helper"
    assert parsed.functions[0].parent_class is None
    assert len(parsed.classes[0].methods) == 1


def test_deeply_nested_function_qualified_name(python_parser: PythonParser) -> None:
    source = (
        "def a():\n"
        "    def b():\n"
        "        def c():\n"
        "            return 1\n"
        "        return c()\n"
        "    return b()\n"
    )

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    names = sorted(f.qualified_name for f in parsed.functions)
    assert names == ["m.a", "m.a.b", "m.a.b.c"]

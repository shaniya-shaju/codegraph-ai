"""Import extraction: plain, aliased, from-imports, relative, wildcard."""

from pathlib import Path

from app.parsing.python.parser import PythonParser


def test_plain_import(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("import os\n", Path("m.py"), "repo-1")

    assert len(parsed.imports) == 1
    imp = parsed.imports[0]
    assert imp.module == "os"
    assert imp.is_from_import is False
    assert imp.alias is None
    assert imp.relative_level == 0


def test_multi_target_plain_import_yields_one_record_per_module(
    python_parser: PythonParser,
) -> None:
    parsed = python_parser.parse("import os, sys\n", Path("m.py"), "repo-1")

    modules = {imp.module for imp in parsed.imports}
    assert modules == {"os", "sys"}


def test_aliased_plain_import(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("import numpy as np\n", Path("m.py"), "repo-1")

    imp = parsed.imports[0]
    assert imp.module == "numpy"
    assert imp.alias == "np"


def test_from_import_single_name(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("from app.services import UserService\n", Path("m.py"), "repo-1")

    imp = parsed.imports[0]
    assert imp.module == "app.services"
    assert imp.imported_names == ["UserService"]
    assert imp.is_from_import is True
    assert imp.relative_level == 0


def test_from_import_with_alias(python_parser: PythonParser) -> None:
    parsed = python_parser.parse(
        "from app.services import UserService as US\n", Path("m.py"), "repo-1"
    )

    imp = parsed.imports[0]
    assert imp.imported_names == ["US"]
    assert imp.alias == "US"


def test_from_import_multiple_names(python_parser: PythonParser) -> None:
    parsed = python_parser.parse(
        "from app.services import UserService, AuthService\n", Path("m.py"), "repo-1"
    )

    imp = parsed.imports[0]
    assert imp.imported_names == ["UserService", "AuthService"]


def test_relative_import_one_level(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("from .models import User\n", Path("app/routes.py"), "repo-1")

    imp = parsed.imports[0]
    assert imp.relative_level == 1
    assert imp.module == "models"
    assert imp.imported_names == ["User"]


def test_relative_import_two_levels(python_parser: PythonParser) -> None:
    parsed = python_parser.parse(
        "from ..core.config import settings\n", Path("app/api/routes.py"), "repo-1"
    )

    imp = parsed.imports[0]
    assert imp.relative_level == 2
    assert imp.module == "core.config"
    assert imp.imported_names == ["settings"]


def test_relative_import_bare_dot_no_module(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("from . import utils\n", Path("app/__init__.py"), "repo-1")

    imp = parsed.imports[0]
    assert imp.relative_level == 1
    assert imp.module is None
    assert imp.imported_names == ["utils"]


def test_wildcard_import(python_parser: PythonParser) -> None:
    parsed = python_parser.parse("from os import *\n", Path("m.py"), "repo-1")

    imp = parsed.imports[0]
    assert imp.imported_names == ["*"]


def test_lazy_import_inside_function_is_still_extracted(python_parser: PythonParser) -> None:
    source = "def f():\n    import json\n    return json\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert [imp.module for imp in parsed.imports] == ["json"]

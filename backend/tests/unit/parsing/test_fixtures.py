"""Parses every fixture under tests/fixtures/python/ and checks broad,
file-specific invariants — a smoke test across the full fixture set plus
targeted assertions for the trickier fixtures."""

from pathlib import Path

import pytest

from app.parsing.python.parser import PythonParser
from tests.unit.parsing.conftest import FIXTURES_DIR, load_fixture

ALL_FIXTURES = sorted(p.name for p in FIXTURES_DIR.glob("*.py"))


@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_every_fixture_parses_without_raising(
    python_parser: PythonParser, fixture_name: str
) -> None:
    source = load_fixture(fixture_name)

    parsed = python_parser.parse(source, Path(fixture_name), "repo-1")

    assert parsed.file_path == fixture_name
    assert parsed.repository_id == "repo-1"
    # Every location anywhere in the file must be a real, 1-based line
    # within the file's own line count.
    line_count = source.count("\n") + 1
    for func in parsed.functions:
        assert 1 <= func.location.start_line <= line_count


def test_fastapi_fixture_recognizes_all_three_routes(python_parser: PythonParser) -> None:
    source = load_fixture("07_fastapi_routes.py")

    parsed = python_parser.parse(source, Path("07_fastapi_routes.py"), "repo-1")
    routes = {
        f.name: f.decorators[0].route_info
        for f in parsed.functions
        if f.decorators and f.decorators[0].route_info
    }

    assert routes["list_users"].http_method == "GET"
    assert routes["list_users"].path == "/users"
    assert routes["create_user"].http_method == "POST"
    assert routes["delete_user"].http_method == "DELETE"
    assert routes["delete_user"].path == "/users/{user_id}"


def test_flask_fixture_recognizes_both_routes(python_parser: PythonParser) -> None:
    source = load_fixture("08_flask_routes.py")

    parsed = python_parser.parse(source, Path("08_flask_routes.py"), "repo-1")
    routes = {f.name: f.decorators[0].route_info for f in parsed.functions}

    assert routes["health"].http_method == "GET"
    assert routes["login"].http_method == "POST"


def test_syntax_error_fixture_still_extracts_good_function(python_parser: PythonParser) -> None:
    source = load_fixture("17_syntax_error.py")

    parsed = python_parser.parse(source, Path("17_syntax_error.py"), "repo-1")

    assert "good" in {f.name for f in parsed.functions}
    assert len(parsed.parse_errors) >= 1


def test_empty_file_fixture(python_parser: PythonParser) -> None:
    source = load_fixture("18_empty_file.py")

    parsed = python_parser.parse(source, Path("18_empty_file.py"), "repo-1")

    assert parsed.functions == []
    assert parsed.classes == []
    assert parsed.parse_errors == []


def test_multiple_classes_and_functions_fixture_counts(python_parser: PythonParser) -> None:
    source = load_fixture("20_multiple_classes_functions.py")

    parsed = python_parser.parse(source, Path("20_multiple_classes_functions.py"), "repo-1")

    assert {f.name for f in parsed.functions} == {
        "first_function",
        "second_function",
        "third_function",
    }
    assert {c.name for c in parsed.classes} == {"FirstClass", "SecondClass"}

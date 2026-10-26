"""Shared helpers for parser unit tests."""

from pathlib import Path

import pytest

from app.parsing.python.parser import PythonParser

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "python"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def python_parser() -> PythonParser:
    return PythonParser()

"""Shared fixtures/helpers for indexing unit tests."""

from pathlib import Path

import pytest

from app.indexing.models import ChunkingLimits
from app.parsing.python.parser import PythonParser


@pytest.fixture
def python_parser() -> PythonParser:
    return PythonParser()


@pytest.fixture
def generous_limits() -> ChunkingLimits:
    """Large enough that ordinary fixture code never triggers fragmentation."""
    return ChunkingLimits(max_characters=4000, max_lines=200, context_lines=3)


@pytest.fixture
def tiny_limits() -> ChunkingLimits:
    """Small enough to force oversized-symbol fragmentation deterministically."""
    return ChunkingLimits(max_characters=80, max_lines=4, context_lines=1)


def parse(
    python_parser: PythonParser, source: str, file_path: str = "m.py", repository_id: str = "repo-1"
):
    return python_parser.parse(source, Path(file_path), repository_id)

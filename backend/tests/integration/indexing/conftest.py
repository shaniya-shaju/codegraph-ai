"""Fixtures for the indexing-layer's integration tests.

Unlike tests/integration/graph (which needs a real, reachable Neo4j),
ChromaDB is embedded — a tmp_path-backed `ChromaVectorStore` here is
already "real" storage/search code, no daemon or network required. The
embedding provider is still the deterministic `FakeEmbeddingProvider`
(see tests/fakes.py) so these tests stay fast and offline; the one test
that exercises the real configured Sentence Transformers model is
separate and explicitly opt-in (test_real_embedding_model.py).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.fakes import FakeEmbeddingProvider

from app.core.config import Settings
from app.indexing.chroma_store import ChromaVectorStore
from app.parsing.python.parser import PythonParser


@pytest.fixture
def indexing_settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        chroma_persist_directory=str(tmp_path / "chroma"),
        chroma_collection_prefix="itest",
        indexing_batch_size=8,
    )


@pytest.fixture
def vector_store(indexing_settings: Settings) -> ChromaVectorStore:
    return ChromaVectorStore(indexing_settings)


@pytest.fixture
def embedding_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def python_parser() -> PythonParser:
    return PythonParser()


def parse(python_parser: PythonParser, source: str, file_path: str, repository_id: str) -> object:
    return python_parser.parse(source, Path(file_path), repository_id)


@pytest.fixture
def db_session(isolated_database: None) -> Iterator[object]:
    """A real SQLite-backed session for the manifest table, isolated per
    test (see the root `isolated_database` fixture)."""
    from app.core.database import get_session_factory

    session = get_session_factory()()
    yield session
    session.close()

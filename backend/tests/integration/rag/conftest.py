"""Fixtures for hybrid-retrieval integration tests.

Needs a **real, reachable Neo4j** (unlike tests/unit/rag, nothing about
the graph side is mocked here) — same as tests/integration/graph. Run
with:

    docker compose up -d neo4j
    cd backend
    NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=changeme \\
        pytest tests/integration/rag -q

(Or just `pytest tests/integration/rag -q` if your shell/`.env` already
has those Neo4j variables pointed at a running instance.)

The vector side uses a real embedded ChromaDB (tmp_path-backed, no daemon
needed) with the deterministic FakeEmbeddingProvider — see
tests/integration/indexing/conftest.py, same rationale.

If Neo4j isn't reachable, every test in this package is skipped with a
visible, explicit reason — see `_require_reachable_neo4j`.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.fakes import FakeEmbeddingProvider

from app.core.config import Settings, get_settings
from app.graph.graph_builder import (
    RepositoryMetadata,
    build_repository_graph,
    delete_repository_graph,
)
from app.graph.neo4j_client import Neo4jClient, reset_neo4j_client
from app.graph.schema import ensure_schema
from app.indexing.chroma_store import ChromaVectorStore
from app.indexing.indexing_service import index_repository
from app.parsing.python.parser import PythonParser

_AUTH_SOURCE = '''"""Authentication helpers."""


def validate_credentials(email: str, password: str) -> bool:
    """Check whether the given credentials are valid."""
    return bool(email and password)


def login(email: str, password: str) -> bool:
    """Authenticate a user by email and password."""
    return validate_credentials(email, password)


def handle_login_request(email: str, password: str) -> bool:
    """API handler that authenticates a login request."""
    return login(email, password)


class AuthService:
    """Base authentication service."""

    def authenticate(self, email: str, password: str) -> bool:
        return login(email, password)


class AdminAuthService(AuthService):
    """Authentication service for admin users."""

    def authenticate(self, email: str, password: str) -> bool:
        return super().authenticate(email, password)
'''

_DB_SOURCE = '''"""Database repository layer."""


class UserRepository:
    """Persists and retrieves user records."""

    def find_by_email(self, email: str) -> dict:
        """Look up a user by email."""
        return {}
'''


@pytest.fixture(scope="session")
def _require_reachable_neo4j() -> None:
    client = Neo4jClient(get_settings())
    if not client.verify_connectivity():
        client.close()
        pytest.skip(
            "No reachable Neo4j at the configured NEO4J_URI — start one with "
            "`docker compose up -d neo4j` and re-run "
            "(see tests/integration/rag/conftest.py for the exact command).",
            allow_module_level=False,
        )
    client.close()


@pytest.fixture
def neo4j_client(_require_reachable_neo4j: None) -> Iterator[Neo4jClient]:
    reset_neo4j_client()
    client = Neo4jClient(get_settings())
    ensure_schema(client)
    yield client
    client.close()


@pytest.fixture
def indexing_settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        chroma_persist_directory=str(tmp_path / "chroma"), chroma_collection_prefix="ragitest"
    )


@pytest.fixture
def vector_store(indexing_settings: Settings) -> ChromaVectorStore:
    return ChromaVectorStore(indexing_settings)


@pytest.fixture
def embedding_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def sample_repository(
    neo4j_client: Neo4jClient,
    vector_store: ChromaVectorStore,
    embedding_provider: FakeEmbeddingProvider,
    indexing_settings: Settings,
    isolated_database: None,
) -> Iterator[str]:
    """A repository_id with a real graph AND a real (fake-embedded)
    vector index built from a small, hand-written sample repository —
    cleaned up from both stores after the test."""
    from app.core.database import get_session_factory

    repository_id = f"itest-rag-{uuid.uuid4()}"
    parser = PythonParser()
    auth_file = parser.parse(_AUTH_SOURCE, Path("app/auth.py"), repository_id)
    db_file = parser.parse(_DB_SOURCE, Path("app/db.py"), repository_id)
    parsed_files = [auth_file, db_file]
    line_counts = {
        "app/auth.py": _AUTH_SOURCE.count("\n") + 1,
        "app/db.py": _DB_SOURCE.count("\n") + 1,
    }

    build_repository_graph(
        neo4j_client,
        RepositoryMetadata(
            repository_id=repository_id,
            name="sample-repo",
            source_type="local_path",
            source_url=None,
            default_branch=None,
            commit_hash=None,
            parser_version="1",
        ),
        parsed_files,
        line_counts,
    )

    session = get_session_factory()()
    index_repository(
        session,
        indexing_settings,
        embedding_provider,
        vector_store,
        repository_id=repository_id,
        parsed_files=parsed_files,
    )
    session.close()

    yield repository_id

    delete_repository_graph(neo4j_client, repository_id)
    vector_store.delete_repository(repository_id)

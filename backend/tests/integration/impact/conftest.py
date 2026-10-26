"""Fixtures for change-impact-analysis integration tests.

Needs a **real, reachable Neo4j** (nothing about the graph side is
mocked here) — same as tests/integration/graph and tests/integration/rag.
Run with:

    docker compose up -d neo4j
    cd backend
    NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=changeme \\
        pytest tests/integration/impact -q

(Or just `pytest tests/integration/impact -q` if your shell/`.env`
already has those Neo4j variables pointed at a running instance.)

If Neo4j isn't reachable, every test in this package is skipped with a
visible, explicit reason — see `_require_reachable_neo4j`. No vector
store is needed here — change-impact analysis is graph-only.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.graph.graph_builder import (
    RepositoryMetadata,
    build_repository_graph,
    delete_repository_graph,
)
from app.graph.neo4j_client import Neo4jClient, reset_neo4j_client
from app.graph.schema import ensure_schema
from app.parsing.python.parser import PythonParser

# The sample graph approximately matches the impact-analysis task's own
# worked integration example:
#
#   POST /login -> HANDLED_BY -> login_endpoint -> CALLS -> authentication_service
#       -> CALLS -> login -> CALLS -> find_by_email
#   admin_login -> CALLS -> login
#
# plus a 3-node CALLS cycle (cyclic_a -> cyclic_b -> cyclic_c -> cyclic_a)
# for traversal-safety testing, and a base/child class pair for
# inheritance-impact testing.
_APP_SOURCE = '''"""Login API with authentication."""

import bcrypt


def find_by_email(email: str) -> dict:
    """Look up a user by email."""
    return {}


def login(email: str, password: str) -> bool:
    """Authenticate a user by email and password."""
    bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    return bool(find_by_email(email))


def authentication_service(email: str, password: str) -> bool:
    """Wraps login for the API layer."""
    return login(email, password)


def admin_login(email: str, password: str) -> bool:
    """Admin-specific login entry point."""
    return login(email, password)


@app.post("/login")
def login_endpoint(email: str, password: str) -> bool:
    """POST /login handler."""
    return authentication_service(email, password)


def cyclic_a() -> bool:
    """Part of an intentional 3-node CALLS cycle."""
    return cyclic_b()


def cyclic_b() -> bool:
    return cyclic_c()


def cyclic_c() -> bool:
    return cyclic_a()


class BaseHandler:
    """Base request handler."""

    def handle(self) -> bool:
        return True


class LoginHandler(BaseHandler):
    """Handles login requests."""

    def handle(self) -> bool:
        return super().handle()
'''

_TEST_SOURCE = '''"""Tests for the login API."""

from app.api import login


def test_login_succeeds() -> None:
    assert login("a@example.com", "pw") in (True, False)
'''


@pytest.fixture(scope="session")
def _require_reachable_neo4j() -> None:
    client = Neo4jClient(get_settings())
    if not client.verify_connectivity():
        client.close()
        pytest.skip(
            "No reachable Neo4j at the configured NEO4J_URI — start one with "
            "`docker compose up -d neo4j` and re-run "
            "(see tests/integration/impact/conftest.py for the exact command).",
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


@dataclass(frozen=True)
class SampleRepository:
    repository_id: str
    symbol_ids: dict[str, str]  # qualified_name -> symbol_id


def _build_sample_repository(neo4j_client: Neo4jClient) -> SampleRepository:
    repository_id = f"itest-impact-{uuid.uuid4()}"
    parser = PythonParser()
    app_file = parser.parse(_APP_SOURCE, Path("app/api.py"), repository_id)
    test_file = parser.parse(_TEST_SOURCE, Path("tests/test_api.py"), repository_id)
    parsed_files = [app_file, test_file]
    line_counts = {
        "app/api.py": _APP_SOURCE.count("\n") + 1,
        "tests/test_api.py": _TEST_SOURCE.count("\n") + 1,
    }

    build_repository_graph(
        neo4j_client,
        RepositoryMetadata(
            repository_id=repository_id,
            name="sample-impact-repo",
            source_type="local_path",
            source_url=None,
            default_branch=None,
            commit_hash=None,
            parser_version="1",
        ),
        parsed_files,
        line_counts,
    )

    symbol_ids: dict[str, str] = {}
    for func in app_file.functions:
        symbol_ids[func.qualified_name] = func.id
    for cls in app_file.classes:
        symbol_ids[cls.qualified_name] = cls.id
        for method in cls.methods:
            symbol_ids[method.qualified_name] = method.id
    for func in test_file.functions:
        symbol_ids[func.qualified_name] = func.id

    return SampleRepository(repository_id=repository_id, symbol_ids=symbol_ids)


@pytest.fixture
def sample_repository(neo4j_client: Neo4jClient) -> Iterator[SampleRepository]:
    sample = _build_sample_repository(neo4j_client)
    yield sample
    delete_repository_graph(neo4j_client, sample.repository_id)


@pytest.fixture
def second_sample_repository(neo4j_client: Neo4jClient) -> Iterator[SampleRepository]:
    """A second, independent repository — used for repository-isolation
    tests (see the impact-analysis task's "second repository remains
    isolated")."""
    sample = _build_sample_repository(neo4j_client)
    yield sample
    delete_repository_graph(neo4j_client, sample.repository_id)

"""Fixtures for the graph-layer's Neo4j integration tests.

These need a **real, reachable Neo4j** — unlike everything under
tests/unit/graph, nothing here is mocked. Run them with:

    docker compose up -d neo4j
    cd backend
    NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=changeme \\
        pytest tests/integration/graph -q

(Or just `pytest tests/integration/graph -q` if your shell/`.env` already
has those Neo4j variables pointed at a running instance — see
.env.example and docker-compose.yml's `neo4j` service, which uses
`NEO4J_AUTH: ${NEO4J_USERNAME:-neo4j}/${NEO4J_PASSWORD:-changeme}`.)

If Neo4j isn't reachable, every test in this package is skipped with a
visible, explicit reason (not silently) — see `_require_reachable_neo4j`.
"""

import uuid
from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.graph.graph_builder import delete_repository_graph
from app.graph.neo4j_client import Neo4jClient, reset_neo4j_client
from app.graph.schema import ensure_schema


@pytest.fixture(scope="session")
def _require_reachable_neo4j() -> None:
    client = Neo4jClient(get_settings())
    if not client.verify_connectivity():
        client.close()
        pytest.skip(
            "No reachable Neo4j at the configured NEO4J_URI — start one with "
            "`docker compose up -d neo4j` and re-run "
            "(see tests/integration/graph/conftest.py for the exact command).",
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
def test_repository_id(neo4j_client: Neo4jClient) -> Iterator[str]:
    """A fresh repository_id, cleaned up from Neo4j after the test —
    never touches any other repository's data (see DELETE_REPOSITORY_GRAPH's
    own repository_id scoping)."""
    repository_id = f"itest-{uuid.uuid4()}"
    yield repository_id
    delete_repository_graph(neo4j_client, repository_id)

"""Fixtures for the end-to-end demo workflow test — needs a **real,
reachable Neo4j** (nothing here is mocked at the graph layer). Run with:

    docker compose up -d neo4j
    cd backend
    NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=changeme \\
        pytest tests/e2e -q

(Or just `pytest tests/e2e -q` if your shell/`.env` already has those
Neo4j variables pointed at a running instance.)

If Neo4j isn't reachable, every test in this package is skipped with a
visible, explicit reason — never faked (see the integration-reliability
task: "Do not claim a live integration test passed if it was skipped or
mocked.").
"""

import pytest

from app.core.config import get_settings
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
            "(see tests/e2e/conftest.py for the exact command).",
            allow_module_level=False,
        )
    client.close()


@pytest.fixture
def neo4j_ready(_require_reachable_neo4j: None) -> None:
    reset_neo4j_client()
    client = Neo4jClient(get_settings())
    ensure_schema(client)
    client.close()

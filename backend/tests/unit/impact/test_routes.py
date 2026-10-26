"""HTTP-level tests for the deterministic impact-analysis endpoint —
uses FastAPI dependency_overrides + FakeNeo4jClient so these run without
a real Neo4j (see tests/unit/impact/conftest.py).

Note: get_symbol/search_symbols (app.graph.repository_graph_service) are
NOT patched here — target resolution goes through the real service code,
so each Neo4jClient.execute_read call must be queued in the shape that
code actually expects: ``{"n": <FakeNode>}`` records, not pre-built
domain models.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routes import impact as impact_routes
from app.main import app
from tests.unit.impact.conftest import FakeNeo4jClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_repository_check():
    app.dependency_overrides[impact_routes._require_repository] = lambda: "repo-1"
    yield
    app.dependency_overrides.pop(impact_routes._require_repository, None)


def _override_graph_client(fake_client: FakeNeo4jClient) -> None:
    app.dependency_overrides[impact_routes._graph_client] = lambda: fake_client


@pytest.fixture(autouse=True)
def _clear_graph_override():
    yield
    app.dependency_overrides.pop(impact_routes._graph_client, None)


class TestGetImpactAnalysis:
    def test_success_returns_deterministic_result(self, fake_node_factory) -> None:
        target = fake_node_factory(id="f1", label="Function", qualified_name="pkg.func")
        queue = [
            [{"n": target}],  # get_symbol
            [],  # callers
            [],  # callees
            [],  # endpoints
            [],
            [],  # external
            [{"in_degree": 0, "out_degree": 0}],  # centrality
        ]
        _override_graph_client(FakeNeo4jClient(queue))

        response = client.get("/api/v1/repositories/repo-1/impact/f1")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["target"]["qualified_name"] == "pkg.func"
        assert body["risk_level"] == "LOW"
        assert body["direct_callers"] == []

    def test_missing_symbol_returns_404(self) -> None:
        _override_graph_client(FakeNeo4jClient([[]]))  # get_symbol -> None
        response = client.get("/api/v1/repositories/repo-1/impact/does-not-exist")
        assert response.status_code == 404
        body = response.json()["error"]
        assert body["code"] == "SYMBOL_NOT_FOUND"
        assert body["retryable"] is False

    def test_unsupported_target_type_returns_400(self, fake_node_factory) -> None:
        module_node = fake_node_factory(id="mod1", label="Module", qualified_name="pkg.mod")
        _override_graph_client(FakeNeo4jClient([[{"n": module_node}]]))
        response = client.get("/api/v1/repositories/repo-1/impact/mod1")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_ambiguous_qualified_name_returns_400_with_candidates(self, fake_node_factory) -> None:
        candidates = [
            {
                "n": fake_node_factory(
                    id="s1", label="Function", name="login", qualified_name="app.auth.service.login"
                )
            },
            {
                "n": fake_node_factory(
                    id="s2", label="Function", name="login", qualified_name="tests.helpers.login"
                )
            },
        ]
        _override_graph_client(FakeNeo4jClient([candidates]))  # search_symbols result
        response = client.get(
            "/api/v1/repositories/repo-1/impact/placeholder", params={"qualified_name": "login"}
        )
        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "AMBIGUOUS_SYMBOL"
        assert "app.auth.service.login" in body["message"]
        assert "tests.helpers.login" in body["message"]
        assert set(body["details"]["candidates"]) == {
            "app.auth.service.login",
            "tests.helpers.login",
        }

    def test_invalid_depth_returns_400(self, fake_node_factory) -> None:
        target = fake_node_factory(id="f1", label="Function", qualified_name="pkg.func")
        _override_graph_client(FakeNeo4jClient([[{"n": target}]]))
        response = client.get("/api/v1/repositories/repo-1/impact/f1", params={"max_depth": 999})
        assert response.status_code == 400

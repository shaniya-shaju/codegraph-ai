"""Bounded read-side queries: traversal-depth validation, result-limit
validation, and repository_id scoping on every call — verified against a
FakeNeo4jClient (no real Neo4j needed)."""

import pytest

from app.core.config import Settings
from app.graph import queries
from app.graph import repository_graph_service as service
from app.graph.exceptions import TraversalLimitExceededError
from tests.unit.graph.conftest import FakeNeo4jClient


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class TestDepthValidation:
    def test_rejects_depth_below_one(self, fake_client: FakeNeo4jClient) -> None:
        with pytest.raises(TraversalLimitExceededError):
            service.get_symbol_neighbors(
                fake_client, _settings(), repository_id="repo-1", symbol_id="s1", depth=0
            )

    def test_rejects_depth_above_configured_max(self, fake_client: FakeNeo4jClient) -> None:
        settings = _settings(graph_max_traversal_depth=3)
        with pytest.raises(TraversalLimitExceededError):
            service.get_symbol_neighbors(
                fake_client, settings, repository_id="repo-1", symbol_id="s1", depth=4
            )

    def test_accepts_depth_within_bounds(self, fake_client: FakeNeo4jClient) -> None:
        settings = _settings(graph_max_traversal_depth=3)
        result = service.get_symbol_neighbors(
            fake_client, settings, repository_id="repo-1", symbol_id="s1", depth=2
        )
        assert result.traversal_depth == 2

    def test_default_depth_used_when_not_specified(self, fake_client: FakeNeo4jClient) -> None:
        settings = _settings(graph_default_traversal_depth=1)
        result = service.get_symbol_neighbors(
            fake_client, settings, repository_id="repo-1", symbol_id="s1", depth=None
        )
        assert result.traversal_depth == 1


class TestLimitValidation:
    def test_rejects_limit_below_one(self, fake_client: FakeNeo4jClient) -> None:
        with pytest.raises(TraversalLimitExceededError):
            service.search_symbols(
                fake_client, _settings(), repository_id="repo-1", query="x", limit=0
            )

    def test_rejects_limit_above_configured_max(self, fake_client: FakeNeo4jClient) -> None:
        settings = _settings(graph_symbol_search_max_limit=50)
        with pytest.raises(TraversalLimitExceededError):
            service.search_symbols(
                fake_client, settings, repository_id="repo-1", query="x", limit=51
            )

    def test_default_limit_used_when_not_specified(self, fake_client: FakeNeo4jClient) -> None:
        settings = _settings(graph_symbol_search_default_limit=15)
        service.search_symbols(fake_client, settings, repository_id="repo-1", query="x", limit=None)

        _query, params = fake_client.read_calls[-1]
        assert params["limit"] == 15


class TestRepositoryScoping:
    def test_search_symbols_always_includes_repository_id(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        service.search_symbols(fake_client, _settings(), repository_id="repo-abc", query="login")

        _query, params = fake_client.read_calls[-1]
        assert params["repository_id"] == "repo-abc"

    def test_get_symbol_scopes_by_repository_id(self, fake_client: FakeNeo4jClient) -> None:
        service.get_symbol(fake_client, repository_id="repo-abc", symbol_id="sym-1")

        query, params = fake_client.read_calls[-1]
        assert query is queries.GET_SYMBOL_BY_ID
        assert params["repository_id"] == "repo-abc"
        assert params["symbol_id"] == "sym-1"

    def test_get_callers_and_callees_are_repository_scoped(
        self, fake_client: FakeNeo4jClient
    ) -> None:
        service.get_callers(fake_client, _settings(), repository_id="repo-abc", symbol_id="sym-1")
        service.get_callees(fake_client, _settings(), repository_id="repo-abc", symbol_id="sym-1")

        for _query, params in fake_client.read_calls:
            assert params["repository_id"] == "repo-abc"


class TestSymbolNotFound:
    def test_get_symbol_returns_none_when_no_rows(self, fake_client: FakeNeo4jClient) -> None:
        result = service.get_symbol(fake_client, repository_id="repo-1", symbol_id="missing")
        assert result is None

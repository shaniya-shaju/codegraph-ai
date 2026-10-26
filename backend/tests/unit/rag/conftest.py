"""Shared fixtures for app.rag unit tests (query analysis, retrieval,
and answer-generation)."""

import pytest

from app.domain.graph.models import GraphStatistics, GraphSubgraph
from app.graph import repository_graph_service
from app.indexing.vector_store import VectorStoreMatch


class FakeVectorStore:
    def __init__(self, matches: list[VectorStoreMatch] | None = None) -> None:
        self._matches = matches or []

    def search(self, repository_id, query_embedding, *, top_k, where=None):  # noqa: ANN001, ANN201
        return self._matches[:top_k]

    def upsert(self, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN201
        raise NotImplementedError

    def delete(self, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN201
        raise NotImplementedError

    def delete_repository(self, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN201
        raise NotImplementedError

    def count(self, repository_id):  # noqa: ANN001, ANN201
        raise NotImplementedError

    def health_check(self) -> str:
        return "ok"


@pytest.fixture
def graph_service_patch(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patches every function app.rag's graph-side components call by
    default, with sensible empty defaults each test can override."""
    empty_subgraph = GraphSubgraph(
        nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
    )
    state: dict[str, object] = {
        "search_symbols": [],
        "get_symbol": None,
        "get_callers": empty_subgraph,
        "get_callees": empty_subgraph,
        "get_dependencies": empty_subgraph,
        "get_symbol_neighbors": empty_subgraph,
        "get_repository_overview": empty_subgraph,
        "get_statistics": GraphStatistics(
            repository_id="repo-1",
            node_counts={},
            relationship_counts={},
            unresolved_call_count=0,
            parse_error_count=0,
        ),
        "find_path": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=1
        ),
    }

    for name in (
        "search_symbols",
        "get_symbol",
        "get_callers",
        "get_callees",
        "get_dependencies",
        "get_symbol_neighbors",
        "get_repository_overview",
        "get_statistics",
        "find_path",
    ):
        monkeypatch.setattr(repository_graph_service, name, lambda *a, _n=name, **k: state[_n])

    return state

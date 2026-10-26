"""Shared fixtures/fakes for app.impact unit tests.

``FakeNode`` implements exactly the subset of neo4j's driver ``Node``
interface ``app.graph.mappers.map_node`` actually uses (``.labels``,
``.get``, ``.items()``) — this exercises the REAL production mapping
code, not a stub of it. ``FakeNeo4jClient`` returns pre-queued
``execute_read`` results in call order, so a test can configure exactly
what each of ``app.impact.traversal``'s (possibly multiple) queries
should return without needing a real Neo4j instance.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.graph import repository_graph_service


class FakeNode(dict):
    """Duck-types neo4j.graph.Node closely enough for map_node()."""

    def __init__(
        self,
        *,
        id: str,
        repository_id: str,
        label: str,
        name: str,
        qualified_name: str | None = None,
        file_path: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        **properties: Any,
    ) -> None:
        super().__init__(
            id=id,
            repository_id=repository_id,
            name=name,
            qualified_name=qualified_name,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            **properties,
        )
        self.labels = [label]


class FakeNeo4jClient:
    """Pass a list of "result batches" — one per expected ``execute_read``
    call, in order. Extra calls beyond the queue return ``[]``."""

    def __init__(self, results_queue: Sequence[list[Mapping[str, Any]]] = ()) -> None:
        self._queue: list[list[Mapping[str, Any]]] = list(results_queue)
        self.queries: list[str] = []
        self.params: list[dict[str, Any]] = []

    def execute_read(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[Mapping[str, Any]]:
        self.queries.append(query)
        self.params.append(parameters or {})
        if not self._queue:
            return []
        return self._queue.pop(0)


@pytest.fixture
def graph_symbol_service_patch(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patches app.graph.repository_graph_service.get_symbol/search_symbols
    (what app.impact.service.resolve_target calls) — mirrors
    tests/unit/rag/conftest.py's graph_service_patch."""
    state: dict[str, object] = {"get_symbol": None, "search_symbols": []}
    monkeypatch.setattr(repository_graph_service, "get_symbol", lambda *a, **k: state["get_symbol"])
    monkeypatch.setattr(
        repository_graph_service, "search_symbols", lambda *a, **k: state["search_symbols"]
    )
    return state


@pytest.fixture
def fake_node_factory():
    def _make(
        *,
        id: str = "sym-1",
        repository_id: str = "repo-1",
        label: str = "Function",
        name: str = "some_func",
        qualified_name: str | None = "pkg.mod.some_func",
        file_path: str | None = "pkg/mod.py",
        start_line: int | None = 10,
        end_line: int | None = 15,
        **properties: Any,
    ) -> FakeNode:
        return FakeNode(
            id=id,
            repository_id=repository_id,
            label=label,
            name=name,
            qualified_name=qualified_name,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            **properties,
        )

    return _make

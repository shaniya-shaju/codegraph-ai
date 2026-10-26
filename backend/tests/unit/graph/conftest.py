"""Test doubles for the graph layer's unit tests — no real Neo4j involved.

FakeNeo4jClient records every (query, parameters) pair it's asked to run
instead of talking to a database, so tests can assert on exactly what
Cypher/parameters graph_builder.py and repository_graph_service.py send —
this is what makes "Cypher query parameterization" and "repository
isolation" checkable without a live Neo4j instance.
"""

from collections.abc import Callable
from typing import TypeVar

import pytest

T = TypeVar("T")


class FakeTransaction:
    def __init__(self, client: "FakeNeo4jClient") -> None:
        self._client = client

    def run(self, query: str, parameters: dict[str, object] | None = None) -> list[object]:
        self._client.write_calls.append((query, dict(parameters or {})))
        return []


class FakeNeo4jClient:
    """Records write calls; returns queued canned responses for reads."""

    def __init__(self) -> None:
        self.write_calls: list[tuple[str, dict[str, object]]] = []
        self.read_calls: list[tuple[str, dict[str, object]]] = []
        self.read_queue: list[list[dict[str, object]]] = []

    def execute_write(
        self, query: str, parameters: dict[str, object] | None = None
    ) -> list[object]:
        self.write_calls.append((query, dict(parameters or {})))
        return []

    def execute_read(self, query: str, parameters: dict[str, object] | None = None) -> list[object]:
        self.read_calls.append((query, dict(parameters or {})))
        if self.read_queue:
            return self.read_queue.pop(0)  # type: ignore[return-value]
        return []

    def run_write_transaction(self, work: Callable[[FakeTransaction], T]) -> T:
        return work(FakeTransaction(self))

    def run_read_transaction(self, work: Callable[[FakeTransaction], T]) -> T:
        return work(FakeTransaction(self))


@pytest.fixture
def fake_client() -> FakeNeo4jClient:
    return FakeNeo4jClient()


class FakeDriverNode:
    """Minimal stand-in for neo4j.graph.Node — only what mappers.py uses."""

    def __init__(self, labels: set[str], properties: dict[str, object]) -> None:
        self.labels = labels
        self._properties = properties

    def get(self, key: str, default: object = None) -> object:
        return self._properties.get(key, default)

    def items(self):  # noqa: ANN201 - matches Mapping.items() duck-typing used by mappers.py
        return self._properties.items()

    def __getitem__(self, key: str) -> object:
        return self._properties[key]


class FakeDriverRelationship:
    """Minimal stand-in for neo4j.graph.Relationship."""

    def __init__(
        self,
        rel_type: str,
        properties: dict[str, object],
        start_node: FakeDriverNode | None,
        end_node: FakeDriverNode | None,
    ) -> None:
        self.type = rel_type
        self._properties = properties
        self.start_node = start_node
        self.end_node = end_node

    def items(self):  # noqa: ANN201
        return self._properties.items()

    def get(self, key: str, default: object = None) -> object:
        return self._properties.get(key, default)

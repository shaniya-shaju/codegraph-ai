"""Wraps app.graph.repository_graph_service — never issues Cypher itself
and never exposes a raw Neo4j driver object (see "Graph retriever
adapter": "Do not allow arbitrary natural-language-to-Cypher" / "Do not
expose arbitrary Cypher generation"). Only the closed
``GraphRetrievalOperation`` set is supported.
"""

from typing import Protocol

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, RelationshipType
from app.domain.graph.models import GraphNode, GraphStatistics, GraphSubgraph, SymbolSearchResult
from app.domain.rag.enums import EvidenceSource, EvidenceType, GraphRetrievalOperation
from app.domain.rag.models import RetrievalEvidence
from app.graph import repository_graph_service
from app.graph.neo4j_client import Neo4jClient

_RELATIONSHIP_TO_EVIDENCE_TYPE = {
    RelationshipType.CALLS: EvidenceType.CALL_RELATIONSHIP,
    RelationshipType.EXTENDS: EvidenceType.INHERITANCE_RELATIONSHIP,
}


class GraphServiceLike(Protocol):
    """The subset of app.graph.repository_graph_service this module
    depends on — lets unit tests inject a fake without touching Neo4j."""

    def search_symbols(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        query: str,
        symbol_type: str | None = None,
        file_path: str | None = None,
        limit: int | None = None,
    ) -> list[SymbolSearchResult]: ...

    def get_symbol(
        self, client: Neo4jClient, *, repository_id: str, symbol_id: str
    ) -> GraphNode | None: ...

    def get_callers(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        symbol_id: str,
        limit: int | None = None,
    ) -> GraphSubgraph: ...

    def get_callees(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        symbol_id: str,
        limit: int | None = None,
    ) -> GraphSubgraph: ...

    def get_dependencies(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        symbol_id: str,
        limit: int | None = None,
    ) -> GraphSubgraph: ...

    def get_symbol_neighbors(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        symbol_id: str,
        depth: int | None = None,
        limit: int | None = None,
    ) -> GraphSubgraph: ...

    def get_repository_overview(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        depth: int | None = None,
        limit: int | None = None,
    ) -> GraphSubgraph: ...

    def find_path(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        repository_id: str,
        source_symbol_id: str,
        target_symbol_id: str,
        max_depth: int | None = None,
    ) -> GraphSubgraph: ...

    def get_statistics(self, client: Neo4jClient, *, repository_id: str) -> GraphStatistics: ...


def _node_summary(node: GraphNode) -> str:
    location = (
        f"{node.file_path}:{node.start_line}-{node.end_line}"
        if node.file_path
        else "unknown location"
    )
    return f"{node.label.value} {node.qualified_name or node.name} ({location})"


def _node_evidence_type(node: GraphNode) -> EvidenceType:
    if node.label == NodeLabel.API_ENDPOINT:
        return EvidenceType.API_ENDPOINT
    if node.label == NodeLabel.MODULE:
        return EvidenceType.MODULE
    if node.label == NodeLabel.FILE:
        return EvidenceType.FILE
    return EvidenceType.SYMBOL


def _node_evidence(
    node: GraphNode,
    *,
    repository_id: str,
    graph_distance: int | None,
    relationship_type: str | None = None,
    operation: str,
    evidence_type: EvidenceType | None = None,
) -> RetrievalEvidence:
    """``evidence_type`` defaults to a mapping from the node's own label
    (SYMBOL/MODULE/FILE/API_ENDPOINT). Callers describing a *relationship*
    to this node (callers/callees/dependencies/inheritance) should pass
    the relationship-derived evidence type explicitly instead — a caller
    of ``login`` is CALL_RELATIONSHIP evidence, not just "a symbol"."""
    return RetrievalEvidence(
        id=f"graph:{operation}:{node.id}",
        repository_id=repository_id,
        evidence_type=evidence_type if evidence_type is not None else _node_evidence_type(node),
        symbol_id=node.id,
        qualified_name=node.qualified_name,
        file_path=node.file_path,
        start_line=node.start_line,
        end_line=node.end_line,
        content=_node_summary(node),
        source=EvidenceSource.GRAPH,
        graph_distance=graph_distance,
        relationship_type=relationship_type,
        metadata={"graph_operation": operation},
    )


def _relationship_evidence_type(relationship_type: RelationshipType) -> EvidenceType:
    return _RELATIONSHIP_TO_EVIDENCE_TYPE.get(
        relationship_type, EvidenceType.DEPENDENCY_RELATIONSHIP
    )


def _edges_to_evidence(
    subgraph: GraphSubgraph, *, repository_id: str, operation: str
) -> list[RetrievalEvidence]:
    nodes_by_id = {node.id: node for node in subgraph.nodes}
    evidence: list[RetrievalEvidence] = []
    for edge in subgraph.edges:
        other_id = edge.target_id if edge.source_id in nodes_by_id else edge.source_id
        other = (
            nodes_by_id.get(other_id)
            or nodes_by_id.get(edge.target_id)
            or nodes_by_id.get(edge.source_id)
        )
        if other is None:
            continue
        evidence.append(
            RetrievalEvidence(
                id=f"graph:{operation}:{edge.id}",
                repository_id=repository_id,
                evidence_type=_relationship_evidence_type(edge.relationship_type),
                symbol_id=other.id,
                qualified_name=other.qualified_name,
                file_path=other.file_path,
                start_line=other.start_line,
                end_line=other.end_line,
                content=_node_summary(other),
                source=EvidenceSource.GRAPH,
                # Repository-overview/neighbor traversal can span multiple
                # hops per returned edge (see repository_graph_service's
                # `neighbor_subgraph_query`) — the exact hop count per edge
                # isn't preserved, so this is deliberately left unknown
                # rather than reported as a false "1".
                graph_distance=None,
                relationship_type=edge.relationship_type.value,
                metadata={"graph_operation": operation},
            )
        )
    return evidence


def _statistics_evidence(stats: GraphStatistics, *, repository_id: str) -> RetrievalEvidence:
    node_summary = ", ".join(
        f"{label}={count}" for label, count in sorted(stats.node_counts.items())
    )
    rel_summary = ", ".join(
        f"{rel}={count}" for rel, count in sorted(stats.relationship_counts.items())
    )
    content = (
        f"Repository statistics — nodes: {node_summary or 'none'}; "
        f"relationships: {rel_summary or 'none'}; "
        f"unresolved_calls={stats.unresolved_call_count}; parse_errors={stats.parse_error_count}"
    )
    return RetrievalEvidence(
        id=f"graph:statistics:{repository_id}",
        repository_id=repository_id,
        evidence_type=EvidenceType.GRAPH_STATISTIC,
        symbol_id=None,
        qualified_name=None,
        file_path=None,
        start_line=None,
        end_line=None,
        content=content,
        source=EvidenceSource.GRAPH,
        metadata={"graph_operation": "repository_overview"},
    )


class GraphRetriever:
    def __init__(
        self,
        client: Neo4jClient,
        settings: Settings,
        *,
        graph_service: GraphServiceLike = repository_graph_service,
    ) -> None:
        self._client = client
        self._settings = settings
        self._graph_service = graph_service

    def run(
        self,
        operation: GraphRetrievalOperation,
        *,
        repository_id: str,
        symbol_id: str | None = None,
        target_symbol_id: str | None = None,
        query: str | None = None,
        depth: int | None = None,
        limit: int | None = None,
    ) -> list[RetrievalEvidence]:
        if operation == GraphRetrievalOperation.SYMBOL_DETAILS:
            return self._symbol_details(repository_id, symbol_id)
        if operation == GraphRetrievalOperation.CALLERS:
            return self._direct_relationship(
                self._graph_service.get_callers, repository_id, symbol_id, limit, "callers"
            )
        if operation == GraphRetrievalOperation.CALLEES:
            return self._direct_relationship(
                self._graph_service.get_callees, repository_id, symbol_id, limit, "callees"
            )
        if operation == GraphRetrievalOperation.DEPENDENCIES:
            return self._direct_relationship(
                self._graph_service.get_dependencies,
                repository_id,
                symbol_id,
                limit,
                "dependencies",
            )
        if operation == GraphRetrievalOperation.INHERITANCE:
            return self._inheritance(repository_id, symbol_id, limit)
        if operation == GraphRetrievalOperation.NEIGHBORS:
            return self._neighbors(repository_id, symbol_id, depth, limit)
        if operation == GraphRetrievalOperation.REPOSITORY_OVERVIEW:
            return self._repository_overview(repository_id, depth, limit)
        if operation == GraphRetrievalOperation.API_HANDLER:
            return self._api_handler(repository_id, query, limit)
        if operation == GraphRetrievalOperation.PATHS:
            return self._paths(repository_id, symbol_id, target_symbol_id, depth)
        return []

    def _symbol_details(self, repository_id: str, symbol_id: str | None) -> list[RetrievalEvidence]:
        if not symbol_id:
            return []
        node = self._graph_service.get_symbol(
            self._client, repository_id=repository_id, symbol_id=symbol_id
        )
        if node is None:
            return []
        return [
            _node_evidence(
                node, repository_id=repository_id, graph_distance=0, operation="symbol_details"
            )
        ]

    def _direct_relationship(
        self,
        fn: object,
        repository_id: str,
        symbol_id: str | None,
        limit: int | None,
        operation: str,
    ) -> list[RetrievalEvidence]:
        if not symbol_id:
            return []
        subgraph: GraphSubgraph = fn(  # type: ignore[operator]
            self._client,
            self._settings,
            repository_id=repository_id,
            symbol_id=symbol_id,
            limit=limit,
        )
        evidence = []
        for node, edge in zip(subgraph.nodes, subgraph.edges, strict=False):
            evidence.append(
                _node_evidence(
                    node,
                    repository_id=repository_id,
                    graph_distance=1,
                    relationship_type=edge.relationship_type.value,
                    operation=operation,
                    evidence_type=_relationship_evidence_type(edge.relationship_type),
                )
            )
        return evidence

    def _inheritance(
        self, repository_id: str, symbol_id: str | None, limit: int | None
    ) -> list[RetrievalEvidence]:
        if not symbol_id:
            return []
        subgraph = self._graph_service.get_dependencies(
            self._client,
            self._settings,
            repository_id=repository_id,
            symbol_id=symbol_id,
            limit=limit,
        )
        evidence = []
        for node, edge in zip(subgraph.nodes, subgraph.edges, strict=False):
            if edge.relationship_type != RelationshipType.EXTENDS:
                continue
            evidence.append(
                _node_evidence(
                    node,
                    repository_id=repository_id,
                    graph_distance=1,
                    relationship_type=edge.relationship_type.value,
                    operation="inheritance",
                    evidence_type=EvidenceType.INHERITANCE_RELATIONSHIP,
                )
            )
        return evidence

    def _neighbors(
        self, repository_id: str, symbol_id: str | None, depth: int | None, limit: int | None
    ) -> list[RetrievalEvidence]:
        if not symbol_id:
            return []
        subgraph = self._graph_service.get_symbol_neighbors(
            self._client,
            self._settings,
            repository_id=repository_id,
            symbol_id=symbol_id,
            depth=depth,
            limit=limit,
        )
        return _edges_to_evidence(subgraph, repository_id=repository_id, operation="neighbors")

    def _repository_overview(
        self, repository_id: str, depth: int | None, limit: int | None
    ) -> list[RetrievalEvidence]:
        subgraph = self._graph_service.get_repository_overview(
            self._client, self._settings, repository_id=repository_id, depth=depth, limit=limit
        )
        evidence = _edges_to_evidence(
            subgraph, repository_id=repository_id, operation="repository_overview"
        )
        stats = self._graph_service.get_statistics(self._client, repository_id=repository_id)
        evidence.append(_statistics_evidence(stats, repository_id=repository_id))
        return evidence

    def _api_handler(
        self, repository_id: str, query: str | None, limit: int | None
    ) -> list[RetrievalEvidence]:
        if not query:
            return []
        endpoints = self._graph_service.search_symbols(
            self._client,
            self._settings,
            repository_id=repository_id,
            query=query,
            symbol_type=NodeLabel.API_ENDPOINT.value,
            limit=limit,
        )
        evidence: list[RetrievalEvidence] = []
        for endpoint in endpoints[:3]:  # bounded — see this operation's docstring
            node = self._graph_service.get_symbol(
                self._client, repository_id=repository_id, symbol_id=endpoint.symbol_id
            )
            if node is not None:
                evidence.append(
                    _node_evidence(
                        node, repository_id=repository_id, graph_distance=0, operation="api_handler"
                    )
                )
            handler_subgraph = self._graph_service.get_symbol_neighbors(
                self._client,
                self._settings,
                repository_id=repository_id,
                symbol_id=endpoint.symbol_id,
                depth=1,
                limit=limit,
            )
            for other_node, edge in zip(
                handler_subgraph.nodes, handler_subgraph.edges, strict=False
            ):
                if (
                    edge.relationship_type != RelationshipType.HANDLED_BY
                    or other_node.id == endpoint.symbol_id
                ):
                    continue
                evidence.append(
                    _node_evidence(
                        other_node,
                        repository_id=repository_id,
                        graph_distance=1,
                        relationship_type=edge.relationship_type.value,
                        operation="api_handler",
                    )
                )
        return evidence

    def _paths(
        self,
        repository_id: str,
        source_symbol_id: str | None,
        target_symbol_id: str | None,
        max_depth: int | None,
    ) -> list[RetrievalEvidence]:
        if not source_symbol_id or not target_symbol_id:
            return []
        subgraph = self._graph_service.find_path(
            self._client,
            self._settings,
            repository_id=repository_id,
            source_symbol_id=source_symbol_id,
            target_symbol_id=target_symbol_id,
            max_depth=max_depth,
        )
        if not subgraph.nodes:
            return []
        path_text = " → ".join(node.qualified_name or node.name for node in subgraph.nodes)
        has_call = any(edge.relationship_type == RelationshipType.CALLS for edge in subgraph.edges)
        first, last = subgraph.nodes[0], subgraph.nodes[-1]
        return [
            RetrievalEvidence(
                id=f"graph:paths:{first.id}:{last.id}",
                repository_id=repository_id,
                evidence_type=EvidenceType.CALL_RELATIONSHIP
                if has_call
                else EvidenceType.DEPENDENCY_RELATIONSHIP,
                symbol_id=last.id,
                qualified_name=last.qualified_name,
                file_path=last.file_path,
                start_line=last.start_line,
                end_line=last.end_line,
                content=f"Path: {path_text}",
                source=EvidenceSource.GRAPH,
                graph_distance=len(subgraph.edges),
                metadata={"graph_operation": "paths", "hop_count": len(subgraph.edges)},
            )
        ]

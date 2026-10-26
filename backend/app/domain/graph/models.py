"""API-independent graph domain models.

See DATA_MODEL.md "Neo4j: knowledge graph schema". These are what
app.graph.repository_graph_service returns and app.api.routes.graph
serializes — never a raw neo4j Record/Node/Relationship (rule 10: "Keep
graph-query responses independent from raw Neo4j driver objects"). See
app.graph.mappers for the Record -> these-models translation.
"""

from dataclasses import dataclass, field

from app.domain.graph.enums import NodeLabel, RelationshipType, SymbolMatchType


@dataclass(frozen=True)
class GraphNode:
    id: str
    repository_id: str
    label: NodeLabel
    name: str
    qualified_name: str | None
    file_path: str | None
    start_line: int | None
    end_line: int | None
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    id: str
    repository_id: str
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphSubgraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    traversal_depth: int
    result_limit: int


@dataclass(frozen=True)
class SymbolSearchResult:
    symbol_id: str
    symbol_type: NodeLabel
    name: str
    qualified_name: str | None
    file_path: str | None
    start_line: int | None
    end_line: int | None
    match_type: SymbolMatchType


@dataclass(frozen=True)
class GraphStatistics:
    repository_id: str
    node_counts: dict[str, int]
    relationship_counts: dict[str, int]
    unresolved_call_count: int
    parse_error_count: int

"""Read-side orchestration: bounded, repository_id-scoped graph queries
for the API layer.

Every traversal enforces a repository_id filter, a maximum depth, and a
maximum result count (see the task's "All graph traversals must
enforce..."). Nothing here ever returns a raw neo4j Node/Relationship —
everything goes through app.graph.mappers into app.domain.graph.models
first (rule 10).
"""

from neo4j import Record

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel
from app.domain.graph.models import (
    GraphEdge,
    GraphNode,
    GraphStatistics,
    GraphSubgraph,
    SymbolSearchResult,
)
from app.graph import queries
from app.graph.exceptions import TraversalLimitExceededError
from app.graph.mappers import (
    map_graph_statistics,
    map_node,
    map_relationship,
    map_symbol_search_result,
)
from app.graph.neo4j_client import Neo4jClient


def _validate_depth(depth: int, settings: Settings) -> int:
    if depth < 1 or depth > settings.graph_max_traversal_depth:
        raise TraversalLimitExceededError(
            f"depth must be between 1 and {settings.graph_max_traversal_depth} (got {depth})."
        )
    return depth


def _validate_limit(limit: int, max_limit: int) -> int:
    if limit < 1 or limit > max_limit:
        raise TraversalLimitExceededError(f"limit must be between 1 and {max_limit} (got {limit}).")
    return limit


def _validate_symbol_type(symbol_type: str | None) -> str | None:
    if symbol_type is None:
        return None
    if symbol_type not in {label.value for label in NodeLabel}:
        raise TraversalLimitExceededError(f"Unknown symbol_type {symbol_type!r}.")
    return symbol_type


def search_symbols(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    query: str,
    symbol_type: str | None = None,
    file_path: str | None = None,
    limit: int | None = None,
) -> list[SymbolSearchResult]:
    limit = _validate_limit(
        limit if limit is not None else settings.graph_symbol_search_default_limit,
        settings.graph_symbol_search_max_limit,
    )
    symbol_type = _validate_symbol_type(symbol_type)

    records = client.execute_read(
        queries.SEARCH_SYMBOLS,
        {
            "repository_id": repository_id,
            "query": query,
            "symbol_type": symbol_type,
            "file_path": file_path,
            "searchable_labels": queries.SEARCHABLE_LABELS,
            "limit": limit,
        },
    )
    return [map_symbol_search_result(record["n"], query) for record in records]


def get_symbol(client: Neo4jClient, *, repository_id: str, symbol_id: str) -> GraphNode | None:
    records = client.execute_read(
        queries.GET_SYMBOL_BY_ID, {"repository_id": repository_id, "symbol_id": symbol_id}
    )
    if not records:
        return None
    return map_node(records[0]["n"])


def get_callers(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    limit: int | None = None,
) -> GraphSubgraph:
    limit = _validate_limit(
        limit if limit is not None else settings.graph_max_nodes, settings.graph_max_nodes
    )
    records = client.execute_read(
        queries.GET_DIRECT_CALLERS,
        {"repository_id": repository_id, "symbol_id": symbol_id, "limit": limit},
    )
    nodes = [map_node(record["caller"]) for record in records]
    edges = [map_relationship(record["r"], repository_id=repository_id) for record in records]
    return GraphSubgraph(
        nodes=nodes,
        edges=edges,
        truncated=len(records) >= limit,
        traversal_depth=1,
        result_limit=limit,
    )


def get_callees(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    limit: int | None = None,
) -> GraphSubgraph:
    limit = _validate_limit(
        limit if limit is not None else settings.graph_max_nodes, settings.graph_max_nodes
    )
    records = client.execute_read(
        queries.GET_DIRECT_CALLEES,
        {"repository_id": repository_id, "symbol_id": symbol_id, "limit": limit},
    )
    nodes = [map_node(record["callee"]) for record in records]
    edges = [map_relationship(record["r"], repository_id=repository_id) for record in records]
    return GraphSubgraph(
        nodes=nodes,
        edges=edges,
        truncated=len(records) >= limit,
        traversal_depth=1,
        result_limit=limit,
    )


def get_dependencies(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    limit: int | None = None,
) -> GraphSubgraph:
    limit = _validate_limit(
        limit if limit is not None else settings.graph_max_nodes, settings.graph_max_nodes
    )
    records = client.execute_read(
        queries.GET_DEPENDENCIES,
        {"repository_id": repository_id, "symbol_id": symbol_id, "limit": limit},
    )
    nodes = [map_node(record["target"]) for record in records]
    edges = [map_relationship(record["r"], repository_id=repository_id) for record in records]
    return GraphSubgraph(
        nodes=nodes,
        edges=edges,
        truncated=len(records) >= limit,
        traversal_depth=1,
        result_limit=limit,
    )


def get_symbol_neighbors(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    depth: int | None = None,
    limit: int | None = None,
) -> GraphSubgraph:
    depth = _validate_depth(
        depth if depth is not None else settings.graph_default_traversal_depth, settings
    )
    limit = _validate_limit(
        limit if limit is not None else settings.graph_max_relationships,
        settings.graph_max_relationships,
    )

    records = client.execute_read(
        queries.neighbor_subgraph_query(depth),
        {"repository_id": repository_id, "symbol_id": symbol_id, "limit": limit},
    )
    return _subgraph_from_root_other_edge_rows(
        records, repository_id=repository_id, depth=depth, limit=limit
    )


def get_repository_overview(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    depth: int | None = None,
    limit: int | None = None,
) -> GraphSubgraph:
    depth = _validate_depth(
        depth if depth is not None else settings.graph_default_traversal_depth, settings
    )
    limit = _validate_limit(
        limit if limit is not None else settings.graph_max_relationships,
        settings.graph_max_relationships,
    )

    records = client.execute_read(
        queries.repository_overview_query(depth), {"repository_id": repository_id, "limit": limit}
    )
    return _subgraph_from_root_other_edge_rows(
        records, repository_id=repository_id, depth=depth, limit=limit
    )


def find_path(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    source_symbol_id: str,
    target_symbol_id: str,
    max_depth: int | None = None,
) -> GraphSubgraph:
    max_depth = _validate_depth(
        max_depth if max_depth is not None else settings.graph_max_traversal_depth, settings
    )

    records = client.execute_read(
        queries.path_between_query(max_depth),
        {
            "repository_id": repository_id,
            "source_symbol_id": source_symbol_id,
            "target_symbol_id": target_symbol_id,
        },
    )
    if not records:
        return GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=max_depth, result_limit=1
        )

    path = records[0]["path"]
    nodes = [map_node(node) for node in path.nodes]
    edges = [map_relationship(rel, repository_id=repository_id) for rel in path.relationships]
    return GraphSubgraph(
        nodes=nodes, edges=edges, truncated=False, traversal_depth=len(edges), result_limit=1
    )


def get_statistics(client: Neo4jClient, *, repository_id: str) -> GraphStatistics:
    node_rows = [
        dict(record)
        for record in client.execute_read(
            queries.GET_GRAPH_STATISTICS_NODE_COUNTS, {"repository_id": repository_id}
        )
    ]
    relationship_rows = [
        dict(record)
        for record in client.execute_read(
            queries.GET_GRAPH_STATISTICS_RELATIONSHIP_COUNTS, {"repository_id": repository_id}
        )
    ]
    unresolved_rows = client.execute_read(
        queries.GET_UNRESOLVED_CALL_COUNT, {"repository_id": repository_id}
    )
    parse_error_rows = client.execute_read(
        queries.GET_PARSE_ERROR_COUNT, {"repository_id": repository_id}
    )

    return map_graph_statistics(
        repository_id=repository_id,
        node_count_rows=node_rows,
        relationship_count_rows=relationship_rows,
        unresolved_call_count=int(unresolved_rows[0]["count"]) if unresolved_rows else 0,
        parse_error_count=int(parse_error_rows[0]["count"]) if parse_error_rows else 0,
    )


def _subgraph_from_root_other_edge_rows(
    records: list[Record], *, repository_id: str, depth: int, limit: int
) -> GraphSubgraph:
    nodes_by_id: dict[str, GraphNode] = {}
    edges_by_id: dict[str, GraphEdge] = {}

    for record in records:
        root_node = map_node(record["root"])
        other_node = map_node(record["other"])
        edge = map_relationship(record["r"], repository_id=repository_id)
        nodes_by_id[root_node.id] = root_node
        nodes_by_id[other_node.id] = other_node
        edges_by_id[edge.id] = edge

    return GraphSubgraph(
        nodes=list(nodes_by_id.values()),
        edges=list(edges_by_id.values()),
        truncated=len(records) >= limit,
        traversal_depth=depth,
        result_limit=limit,
    )

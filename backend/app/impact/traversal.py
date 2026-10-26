"""Bounded, repository_id-scoped Cypher for change-impact analysis.

Reuses ``app.graph.neo4j_client.Neo4jClient`` for query execution and
``app.graph.mappers.map_node`` / ``app.domain.graph`` models for
Record -> domain-model translation — this module never opens its own
driver/session and never returns a raw ``neo4j`` object (same rule as
``app.graph.repository_graph_service``, which this package deliberately
does not duplicate: these queries are impact-analysis-specific traversals
that repository_graph_service doesn't need, so they live here instead of
being bolted onto that module).

Every traversal is scoped by ``repository_id`` and bounded by an
explicitly validated ``depth``/``limit`` (see "Bounded graph traversal":
"Every traversal must enforce repository ID." / "Handle graph cycles
safely."). Cypher's variable-length relationship matching (``*1..N``)
applies relationship uniqueness within one path and is hard-bounded by
``N``, so a cycle like ``A CALLS B CALLS C CALLS A`` can never cause
unbounded traversal — see the module tests for an explicit regression
check.

The one deliberate literal (non-``$parameter``) interpolation is the
variable-length hop bound itself, exactly like
``app.graph.queries.neighbor_subgraph_query`` — Cypher has no parameter
syntax for a pattern's hop-count bound, and the value is always a
plain, already-range-validated ``int`` by the time it reaches an f-string
here, never a raw request value.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.graph.models import GraphNode
from app.graph.mappers import map_node
from app.graph.neo4j_client import Neo4jClient
from app.impact.exceptions import InvalidImpactParameterError

# --- validation --------------------------------------------------------


def validate_depth(depth: int, settings: Settings) -> int:
    if depth < 1 or depth > settings.impact_max_depth:
        raise InvalidImpactParameterError(
            f"max_depth must be between 1 and {settings.impact_max_depth} (got {depth})."
        )
    return depth


def validate_max_nodes(max_nodes: int, settings: Settings) -> int:
    if max_nodes < 1 or max_nodes > settings.impact_max_nodes:
        raise InvalidImpactParameterError(
            f"max_nodes must be between 1 and {settings.impact_max_nodes} (got {max_nodes})."
        )
    return max_nodes


# --- raw traversal rows --------------------------------------------------


@dataclass(frozen=True)
class PathRow:
    """One shortest-so-far path from a traversal query — the analyzer
    reduces these to one (minimum-distance) row per node."""

    node: GraphNode
    distance: int
    path_qualified_names: list[str]
    path_ids: list[str]


@dataclass(frozen=True)
class EndpointImpactRow:
    endpoint: GraphNode
    handler: GraphNode
    distance: int


@dataclass(frozen=True)
class InheritanceRow:
    node: GraphNode
    distance: int


@dataclass(frozen=True)
class ExternalDependencyRow:
    node: GraphNode
    via: str  # "direct" | "containing_file"


# --- queries -------------------------------------------------------------


def _path_names_and_ids(record: object, key_prefix: str) -> tuple[list[str], list[str]]:
    names = [str(n) if n is not None else "" for n in record[f"{key_prefix}_names"]]  # type: ignore[index]
    ids = [str(n) for n in record[f"{key_prefix}_ids"]]  # type: ignore[index]
    return names, ids


def get_upstream_callers(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    max_depth: int,
    max_paths: int,
) -> list[PathRow]:
    """Direct + transitive callers of ``symbol_id`` (``A -[:CALLS]-> ... ->
    target``), one row per distinct path, closest-first. The target itself
    is excluded even if a cycle makes it technically reachable from
    itself."""
    depth = validate_depth(max_depth, settings)
    query = f"""
MATCH p = (caller)-[:CALLS*1..{depth}]->(target {{repository_id: $repository_id, id: $symbol_id}})
WHERE caller.repository_id = $repository_id AND caller.id <> $symbol_id
WITH caller, p, length(p) AS distance
RETURN caller, distance,
       [n IN nodes(p) | coalesce(n.qualified_name, n.name)] AS path_names,
       [n IN nodes(p) | n.id] AS path_ids
ORDER BY distance ASC
LIMIT $limit
"""
    records = client.execute_read(
        query, {"repository_id": repository_id, "symbol_id": symbol_id, "limit": max_paths}
    )
    rows = []
    for record in records:
        names, ids = _path_names_and_ids(record, "path")
        rows.append(
            PathRow(
                node=map_node(record["caller"]),
                distance=int(record["distance"]),
                path_qualified_names=names,
                path_ids=ids,
            )
        )
    return rows


def get_downstream_callees(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    max_depth: int,
    max_paths: int,
) -> list[PathRow]:
    """What ``symbol_id`` itself calls (``target -[:CALLS]-> ... ->
    callee``) — its own downstream dependencies, kept separate from
    upstream dependents (see "Downstream dependency analysis": "These are
    not necessarily 'affected callers.'")."""
    depth = validate_depth(max_depth, settings)
    query = f"""
MATCH p = (target {{repository_id: $repository_id, id: $symbol_id}})-[:CALLS*1..{depth}]->(callee)
WHERE callee.repository_id = $repository_id AND callee.id <> $symbol_id
WITH callee, p, length(p) AS distance
RETURN callee, distance,
       [n IN nodes(p) | coalesce(n.qualified_name, n.name)] AS path_names,
       [n IN nodes(p) | n.id] AS path_ids
ORDER BY distance ASC
LIMIT $limit
"""
    records = client.execute_read(
        query, {"repository_id": repository_id, "symbol_id": symbol_id, "limit": max_paths}
    )
    rows = []
    for record in records:
        names, ids = _path_names_and_ids(record, "path")
        rows.append(
            PathRow(
                node=map_node(record["callee"]),
                distance=int(record["distance"]),
                path_qualified_names=names,
                path_ids=ids,
            )
        )
    return rows


def get_affected_endpoints(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str,
    max_depth: int,
    max_paths: int,
) -> list[EndpointImpactRow]:
    """API endpoints whose handler either IS the target (distance 0) or
    transitively calls it (``*0..depth`` includes the zero-length,
    handler-is-target case) — see "API endpoint impact"."""
    depth = validate_depth(max_depth, settings)
    query = f"""
MATCH (endpoint:APIEndpoint {{repository_id: $repository_id}})-[:HANDLED_BY]->(handler)
WHERE handler.repository_id = $repository_id
MATCH p = (handler)-[:CALLS*0..{depth}]->(target {{repository_id: $repository_id, id: $symbol_id}})
RETURN endpoint, handler, length(p) AS distance
ORDER BY distance ASC
LIMIT $limit
"""
    records = client.execute_read(
        query, {"repository_id": repository_id, "symbol_id": symbol_id, "limit": max_paths}
    )
    return [
        EndpointImpactRow(
            endpoint=map_node(record["endpoint"]),
            handler=map_node(record["handler"]),
            distance=int(record["distance"]),
        )
        for record in records
    ]


def get_inheriting_classes(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    class_id: str,
    max_depth: int,
    max_paths: int,
) -> list[InheritanceRow]:
    """Classes that (transitively) EXTENDS the target class."""
    depth = validate_depth(max_depth, settings)
    query = f"""
MATCH p = (child:Class)-[:EXTENDS*1..{depth}]->(base:Class {{
    repository_id: $repository_id, id: $class_id
}})
WHERE child.repository_id = $repository_id
RETURN child, length(p) AS distance
ORDER BY distance ASC
LIMIT $limit
"""
    records = client.execute_read(
        query, {"repository_id": repository_id, "class_id": class_id, "limit": max_paths}
    )
    return [
        InheritanceRow(node=map_node(record["child"]), distance=int(record["distance"]))
        for record in records
    ]


def get_base_classes(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    class_id: str,
    max_depth: int,
    max_paths: int,
) -> list[InheritanceRow]:
    """Classes the target class (transitively) EXTENDS."""
    depth = validate_depth(max_depth, settings)
    query = f"""
MATCH p = (child:Class {{
    repository_id: $repository_id, id: $class_id
}})-[:EXTENDS*1..{depth}]->(base:Class)
WHERE base.repository_id = $repository_id
RETURN base, length(p) AS distance
ORDER BY distance ASC
LIMIT $limit
"""
    records = client.execute_read(
        query, {"repository_id": repository_id, "class_id": class_id, "limit": max_paths}
    )
    return [
        InheritanceRow(node=map_node(record["base"]), distance=int(record["distance"]))
        for record in records
    ]


def get_owning_class(
    client: Neo4jClient, *, repository_id: str, method_id: str
) -> GraphNode | None:
    """The Class that DEFINES the given method_id, if any — used so a
    METHOD target can still surface inheritance impact via its class."""
    records = client.execute_read(
        """
MATCH (owner:Class {repository_id: $repository_id})
      -[:DEFINES]->(method {repository_id: $repository_id, id: $method_id})
RETURN owner
LIMIT 1
""",
        {"repository_id": repository_id, "method_id": method_id},
    )
    if not records:
        return None
    return map_node(records[0]["owner"])


def get_external_dependencies(
    client: Neo4jClient, *, repository_id: str, symbol_id: str, limit: int
) -> list[ExternalDependencyRow]:
    """External dependencies the graph deterministically knows the target
    interacts with: either a direct DEPENDS_ON edge from the symbol
    itself (currently only emitted for unresolved base classes — see
    graph_builder.py), or an IMPORTS edge from the file that defines it
    (labeled distinctly as "containing_file", never conflated with a
    direct call — see "Do NOT infer... Work only with the graph facts
    that currently exist.")."""
    direct = client.execute_read(
        """
MATCH (source {repository_id: $repository_id, id: $symbol_id})
      -[:DEPENDS_ON]->(dep:ExternalDependency)
RETURN DISTINCT dep
LIMIT $limit
""",
        {"repository_id": repository_id, "symbol_id": symbol_id, "limit": limit},
    )
    via_file = client.execute_read(
        """
MATCH (f:File {repository_id: $repository_id})
      -[:DEFINES*1..3]->(source {repository_id: $repository_id, id: $symbol_id})
MATCH (f)-[:IMPORTS]->(dep:ExternalDependency)
RETURN DISTINCT dep
LIMIT $limit
""",
        {"repository_id": repository_id, "symbol_id": symbol_id, "limit": limit},
    )
    rows = [ExternalDependencyRow(node=map_node(r["dep"]), via="direct") for r in direct]
    seen_ids = {row.node.id for row in rows}
    for record in via_file:
        node = map_node(record["dep"])
        if node.id in seen_ids:
            continue
        seen_ids.add(node.id)
        rows.append(ExternalDependencyRow(node=node, via="containing_file"))
    return rows


def get_local_centrality(
    client: Neo4jClient, *, repository_id: str, symbol_id: str
) -> tuple[int, int]:
    """(in_degree, out_degree) of CALLS edges touching the target — a
    simple *local structural centrality* approximation (incoming +
    outgoing dependency edges), NOT PageRank or any comprehensive
    centrality measure (see "Graph centrality")."""
    records = client.execute_read(
        """
MATCH (target {repository_id: $repository_id, id: $symbol_id})
OPTIONAL MATCH (target)<-[in_rel:CALLS]-()
OPTIONAL MATCH (target)-[out_rel:CALLS]->()
RETURN count(DISTINCT in_rel) AS in_degree, count(DISTINCT out_rel) AS out_degree
""",
        {"repository_id": repository_id, "symbol_id": symbol_id},
    )
    if not records:
        return (0, 0)
    return (int(records[0]["in_degree"]), int(records[0]["out_degree"]))

"""The deterministic change-impact-analysis core — ties bounded graph
traversal, file/module aggregation, signal computation, and risk scoring
together into one ``ImpactAnalysisResult``. This module never calls an
LLM and never imports anything from ``app.rag`` (see the high-level
architecture: "The deterministic ImpactAnalysisResult must exist
independently of any LLM.").

Assumes the target has already been resolved to a single, validated
``GraphNode`` of a supported type — see ``app.impact.service`` for
symbol_id/qualified_name resolution and ambiguity handling, which happens
one layer up.
"""

import time

from app.core.config import Settings
from app.domain.graph.models import GraphNode
from app.domain.impact.enums import ImpactTargetType, ImpactType, TestRelationshipStatus
from app.domain.impact.models import (
    ImpactAnalysisResult,
    ImpactDiagnostics,
    ImpactedEndpoint,
    ImpactedSymbol,
)
from app.graph.neo4j_client import Neo4jClient
from app.impact import aggregator, mappers, risk_scorer, signals, traversal
from app.impact.signals import SignalInputs
from app.impact.traversal import EndpointImpactRow, PathRow


def _reduce_to_min_distance(rows: list[PathRow]) -> list[PathRow]:
    """Rows are already ORDER BY distance ASC from Cypher — keep only the
    first (= shortest) row seen per node id, so a diamond-shaped or
    multi-path dependency graph reports one entry per symbol, not one per
    path."""
    best: dict[str, PathRow] = {}
    for row in rows:
        best.setdefault(row.node.id, row)
    return list(best.values())


def _reduce_endpoints(rows: list[EndpointImpactRow]) -> list[EndpointImpactRow]:
    best: dict[str, EndpointImpactRow] = {}
    for row in rows:
        if row.endpoint.id not in best or row.distance < best[row.endpoint.id].distance:
            best[row.endpoint.id] = row
    return sorted(best.values(), key=lambda r: (r.distance, r.endpoint.id))


def _dedupe_symbols(symbols: list[ImpactedSymbol]) -> list[ImpactedSymbol]:
    seen: dict[str, ImpactedSymbol] = {}
    for symbol in symbols:
        seen.setdefault(symbol.symbol_id, symbol)
    return list(seen.values())


def _has_cycle(row: PathRow) -> bool:
    return len(set(row.path_ids)) < len(row.path_ids)


def analyze_impact(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    target_node: GraphNode,
    target_type: ImpactTargetType,
    max_depth: int | None = None,
    max_nodes: int | None = None,
    include_downstream: bool = True,
    include_tests: bool = True,
) -> ImpactAnalysisResult:
    started = time.monotonic()

    depth = traversal.validate_depth(
        max_depth if max_depth is not None else settings.impact_default_depth, settings
    )
    node_cap = traversal.validate_max_nodes(
        max_nodes if max_nodes is not None else settings.impact_default_max_nodes, settings
    )
    max_paths = settings.impact_max_paths

    target_qn = target_node.qualified_name or target_node.name

    # --- upstream: who is affected if the target changes -----------------
    raw_caller_rows = traversal.get_upstream_callers(
        client,
        settings,
        repository_id=repository_id,
        symbol_id=target_node.id,
        max_depth=depth,
        max_paths=max_paths,
    )
    reduced_callers = _reduce_to_min_distance(raw_caller_rows)
    paths_truncated = len(raw_caller_rows) >= max_paths
    nodes_truncated = len(reduced_callers) > node_cap
    reduced_callers = sorted(reduced_callers, key=lambda r: (r.distance, r.node.id))[:node_cap]

    caller_symbols = [
        mappers.caller_row_to_impacted_symbol(row, target_qualified_name=target_qn)
        for row in reduced_callers
    ]
    direct_callers = [s for s in caller_symbols if s.distance == 1]
    transitive_dependents = [s for s in caller_symbols if s.distance > 1]

    # --- downstream: what the target itself depends on --------------------
    downstream_dependencies: list[ImpactedSymbol] = []
    if include_downstream:
        raw_callee_rows = traversal.get_downstream_callees(
            client,
            settings,
            repository_id=repository_id,
            symbol_id=target_node.id,
            max_depth=depth,
            max_paths=max_paths,
        )
        reduced_callees = _reduce_to_min_distance(raw_callee_rows)
        paths_truncated = paths_truncated or len(raw_callee_rows) >= max_paths
        nodes_truncated = nodes_truncated or len(reduced_callees) > node_cap
        reduced_callees = sorted(reduced_callees, key=lambda r: (r.distance, r.node.id))[:node_cap]
        downstream_dependencies = [
            mappers.callee_row_to_impacted_symbol(row, target_qualified_name=target_qn)
            for row in reduced_callees
        ]
    else:
        raw_callee_rows = []

    # --- API endpoint impact ----------------------------------------------
    raw_endpoint_rows = traversal.get_affected_endpoints(
        client,
        settings,
        repository_id=repository_id,
        symbol_id=target_node.id,
        max_depth=depth,
        max_paths=max_paths,
    )
    reduced_endpoints = _reduce_endpoints(raw_endpoint_rows)
    affected_endpoints: list[ImpactedEndpoint] = [
        mappers.endpoint_row_to_impacted_endpoint(row) for row in reduced_endpoints
    ]
    endpoint_handler_symbols = [
        ImpactedSymbol(
            symbol_id=row.handler.id,
            qualified_name=row.handler.qualified_name,
            symbol_type=row.handler.label.value,
            file_path=row.handler.file_path,
            start_line=row.handler.start_line,
            end_line=row.handler.end_line,
            impact_type=ImpactType.API_ENDPOINT,
            distance=row.distance,
            reason=f"Handles API endpoint {row.endpoint.properties.get('http_method', '')} "
            f"{row.endpoint.properties.get('route_path', '')}.",
        )
        for row in reduced_endpoints
        if row.handler.id != target_node.id
    ]

    # --- inheritance --------------------------------------------------------
    inheriting_classes: list[ImpactedSymbol] = []
    base_classes: list[ImpactedSymbol] = []
    inheritance_root_qn: str | None = None
    class_id: str | None = None
    if target_type is ImpactTargetType.CLASS:
        class_id = target_node.id
        inheritance_root_qn = target_qn
    elif target_type is ImpactTargetType.METHOD:
        owning_class = traversal.get_owning_class(
            client, repository_id=repository_id, method_id=target_node.id
        )
        if owning_class is not None:
            class_id = owning_class.id
            inheritance_root_qn = owning_class.qualified_name or owning_class.name

    if class_id is not None:
        inheriting_rows = traversal.get_inheriting_classes(
            client,
            settings,
            repository_id=repository_id,
            class_id=class_id,
            max_depth=depth,
            max_paths=max_paths,
        )
        base_rows = traversal.get_base_classes(
            client,
            settings,
            repository_id=repository_id,
            class_id=class_id,
            max_depth=depth,
            max_paths=max_paths,
        )
        inheriting_classes = [
            mappers.inheriting_class_row_to_impacted_symbol(
                row, target_qualified_name=inheritance_root_qn
            )
            for row in _dedupe_inheritance(inheriting_rows)
        ]
        base_classes = [
            mappers.base_class_row_to_impacted_symbol(
                row, target_qualified_name=inheritance_root_qn
            )
            for row in _dedupe_inheritance(base_rows)
        ]
    inheritance_impacts = inheriting_classes + base_classes

    # --- external dependencies ----------------------------------------------
    external_rows = traversal.get_external_dependencies(
        client, repository_id=repository_id, symbol_id=target_node.id, limit=node_cap
    )

    # --- local centrality -----------------------------------------------------
    in_degree, out_degree = traversal.get_local_centrality(
        client, repository_id=repository_id, symbol_id=target_node.id
    )

    # --- file / module aggregation -------------------------------------------
    dependent_pool = direct_callers + transitive_dependents + inheriting_classes
    aggregation_pool = _dedupe_symbols(
        [s for s in dependent_pool if s.symbol_id != target_node.id]
        + [s for s in endpoint_handler_symbols if s.symbol_id != target_node.id]
    )
    affected_files = aggregator.aggregate_files(aggregation_pool)
    affected_modules = aggregator.aggregate_modules(aggregation_pool)

    target_module = mappers.module_of(
        target_node.qualified_name, fallback_file_path=target_node.file_path
    )
    cross_module_count = sum(
        1
        for s in direct_callers + transitive_dependents
        if mappers.module_of(s.qualified_name, fallback_file_path=s.file_path) != target_module
    )

    truncated = paths_truncated or nodes_truncated

    # --- test references -------------------------------------------------------
    if include_tests:
        related_tests, test_status = aggregator.classify_test_references(
            direct_callers + transitive_dependents, truncated=truncated
        )
    else:
        related_tests, test_status = [], TestRelationshipStatus.UNKNOWN

    # --- signals + risk score -----------------------------------------------------
    signal_inputs = SignalInputs(
        direct_caller_count=len(direct_callers),
        transitive_dependent_count=len(transitive_dependents),
        affected_file_count=len(affected_files),
        affected_module_count=len(affected_modules),
        api_endpoint_count=len(affected_endpoints),
        cross_module_dependent_count=cross_module_count,
        external_dependency_count=len(external_rows),
        inheritance_impact_count=len(inheritance_impacts),
        centrality_in_degree=in_degree,
        centrality_out_degree=out_degree,
        test_relationship_status=test_status,
    )
    risk_signals = signals.compute_signals(signal_inputs, settings)
    risk_score = risk_scorer.compute_risk_score(risk_signals)
    risk_level = risk_scorer.classify_risk_level(risk_score, settings)

    # --- limitations (only those that actually apply) --------------------------
    limitations = [
        "The structural risk score is a heuristic and has not yet been empirically calibrated.",
        "Dynamic Python calls (e.g. getattr-based dispatch) may not be represented in the "
        "graph, so this result may under-count real callers.",
    ]
    if target_type in (ImpactTargetType.FUNCTION, ImpactTargetType.METHOD):
        limitations.append("Monkey-patched methods cannot be resolved statically.")
    if inheritance_impacts:
        limitations.append("Polymorphic dispatch may produce additional runtime callers.")
    if external_rows or downstream_dependencies:
        limitations.append(
            "Runtime dependency injection may introduce dependencies not visible in the graph."
        )
    if truncated:
        limitations.append(
            "Traversal was truncated at the configured depth/node/path limit — some real "
            "dependents may not be shown."
        )
    if not include_downstream:
        limitations.append("Downstream dependency analysis was skipped for this request.")
    if not include_tests:
        limitations.append("Test-reference detection was skipped for this request.")

    total_impacted_symbols = len(
        {
            s.symbol_id
            for s in direct_callers
            + transitive_dependents
            + downstream_dependencies
            + inheriting_classes
            + base_classes
        }
    )

    cycles_detected = sum(1 for row in raw_caller_rows + raw_callee_rows if _has_cycle(row))
    nodes_visited = len(
        {target_node.id}
        | {r.node.id for r in raw_caller_rows}
        | {r.node.id for r in raw_callee_rows}
        | {r.endpoint.id for r in raw_endpoint_rows}
        | {r.handler.id for r in raw_endpoint_rows}
    )
    edges_traversed = (
        sum(r.distance for r in raw_caller_rows)
        + sum(r.distance for r in raw_callee_rows)
        + sum(max(r.distance, 1) for r in raw_endpoint_rows)
    )
    paths_examined = len(raw_caller_rows) + len(raw_callee_rows) + len(raw_endpoint_rows)

    truncated_reason = None
    if paths_truncated:
        truncated_reason = f"paths_examined reached impact_max_paths ({max_paths})"
    elif nodes_truncated:
        truncated_reason = f"impacted node count reached max_nodes ({node_cap})"

    diagnostics = ImpactDiagnostics(
        analysis_duration_ms=int((time.monotonic() - started) * 1000),
        nodes_visited=nodes_visited,
        edges_traversed=edges_traversed,
        paths_examined=paths_examined,
        cycles_detected=cycles_detected,
        truncated_reason=truncated_reason,
    )

    return ImpactAnalysisResult(
        repository_id=repository_id,
        target=mappers.to_impact_target(target_node, target_type),
        risk_score=risk_score,
        risk_level=risk_level,
        risk_signals=risk_signals,
        direct_callers=direct_callers,
        transitive_dependents=transitive_dependents,
        downstream_dependencies=downstream_dependencies,
        affected_endpoints=affected_endpoints,
        affected_files=affected_files,
        affected_modules=affected_modules,
        inheritance_impacts=inheritance_impacts,
        inheriting_classes=inheriting_classes,
        base_classes=base_classes,
        related_tests=related_tests,
        test_relationship_status=test_status,
        traversal_depth=depth,
        total_impacted_symbols=total_impacted_symbols,
        truncated=truncated,
        limitations=limitations,
        diagnostics=diagnostics,
    )


def _dedupe_inheritance(rows: list[traversal.InheritanceRow]) -> list[traversal.InheritanceRow]:
    best: dict[str, traversal.InheritanceRow] = {}
    for row in rows:
        if row.node.id not in best or row.distance < best[row.node.id].distance:
            best[row.node.id] = row
    return sorted(best.values(), key=lambda r: (r.distance, r.node.id))

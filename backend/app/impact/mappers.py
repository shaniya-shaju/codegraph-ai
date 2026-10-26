"""Translation between raw ``app.impact.traversal`` rows and
``app.domain.impact`` models — including the human-readable ``reason``
every ``ImpactedSymbol`` must carry (see "Every impacted symbol must
explain WHY it is included.").

Also includes ``impact_result_to_evidence`` — a translation from a
finished, deterministic ``ImpactAnalysisResult`` into the same
``RetrievalEvidence`` shape ``app.rag`` already knows how to cite, used by
the natural-language integration (see "Natural-language integration").
This module only depends on ``app.domain.rag`` (plain typed dataclasses,
no LLM/provider code) — never on ``app.rag`` itself, so the deterministic
``app.impact`` package stays independent of any LLM machinery.
"""

from app.domain.graph.enums import NodeLabel
from app.domain.graph.models import GraphNode
from app.domain.impact.enums import ImpactTargetType, ImpactType
from app.domain.impact.models import (
    ImpactAnalysisResult,
    ImpactedEndpoint,
    ImpactedSymbol,
    ImpactTarget,
)
from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.rag.models import RetrievalEvidence
from app.impact.traversal import EndpointImpactRow, InheritanceRow, PathRow

_TARGET_TYPE_BY_LABEL: dict[NodeLabel, ImpactTargetType] = {
    NodeLabel.FUNCTION: ImpactTargetType.FUNCTION,
    NodeLabel.METHOD: ImpactTargetType.METHOD,
    NodeLabel.CLASS: ImpactTargetType.CLASS,
    NodeLabel.API_ENDPOINT: ImpactTargetType.API_ENDPOINT,
}


def target_type_for_label(label: NodeLabel) -> ImpactTargetType | None:
    return _TARGET_TYPE_BY_LABEL.get(label)


def to_impact_target(node: GraphNode, target_type: ImpactTargetType) -> ImpactTarget:
    return ImpactTarget(
        symbol_id=node.id,
        qualified_name=node.qualified_name,
        name=node.name,
        target_type=target_type,
        file_path=node.file_path,
        start_line=node.start_line,
        end_line=node.end_line,
    )


def module_of(qualified_name: str | None, *, fallback_file_path: str | None) -> str:
    """Best-effort module name, derived deterministically from a symbol's
    own qualified_name (its qualified-name package prefix) — never a
    separate query. Falls back to the file path's directory when no
    qualified_name is available (e.g. an APIEndpoint)."""
    if qualified_name and "." in qualified_name:
        return qualified_name.rsplit(".", 1)[0]
    if qualified_name:
        return qualified_name
    if fallback_file_path:
        return fallback_file_path.rsplit("/", 1)[0] if "/" in fallback_file_path else "."
    return "<unknown>"


def caller_row_to_impacted_symbol(
    row: PathRow, *, target_qualified_name: str | None
) -> ImpactedSymbol:
    impact_type = ImpactType.DIRECT_CALLER if row.distance == 1 else ImpactType.TRANSITIVE_CALLER
    target_display = target_qualified_name or "the target symbol"
    if row.distance == 1:
        reason = f"Directly calls {target_display}."
    else:
        via = (
            " via " + " -> ".join(row.path_qualified_names[1:-1])
            if len(row.path_qualified_names) > 2
            else ""
        )
        reason = f"Depends on {target_display} through a chain of {row.distance} calls{via}."
    return ImpactedSymbol(
        symbol_id=row.node.id,
        qualified_name=row.node.qualified_name,
        symbol_type=row.node.label.value,
        file_path=row.node.file_path,
        start_line=row.node.start_line,
        end_line=row.node.end_line,
        impact_type=impact_type,
        distance=row.distance,
        reason=reason,
        path=row.path_qualified_names,
        relationship_path=["CALLS"] * row.distance,
    )


def callee_row_to_impacted_symbol(
    row: PathRow, *, target_qualified_name: str | None
) -> ImpactedSymbol:
    target_display = target_qualified_name or "The target symbol"
    if row.distance == 1:
        reason = f"{target_display} directly calls this symbol."
    else:
        reason = f"{target_display} depends on this symbol through a chain of {row.distance} calls."
    return ImpactedSymbol(
        symbol_id=row.node.id,
        qualified_name=row.node.qualified_name,
        symbol_type=row.node.label.value,
        file_path=row.node.file_path,
        start_line=row.node.start_line,
        end_line=row.node.end_line,
        impact_type=ImpactType.CALLEE,
        distance=row.distance,
        reason=reason,
        path=row.path_qualified_names,
        relationship_path=["CALLS"] * row.distance,
    )


def endpoint_row_to_impacted_endpoint(row: EndpointImpactRow) -> ImpactedEndpoint:
    handler_name = row.handler.qualified_name or row.handler.name
    if row.distance == 0:
        reason = "Endpoint handler directly calls the changed symbol."
    else:
        reason = (
            f"Endpoint handler {handler_name} transitively depends on the changed symbol "
            f"through {row.distance} call(s)."
        )
    return ImpactedEndpoint(
        endpoint_id=row.endpoint.id,
        http_method=str(row.endpoint.properties.get("http_method", "")),
        route_path=str(row.endpoint.properties.get("route_path", "")),
        handler_symbol_id=row.handler.id,
        handler_qualified_name=row.handler.qualified_name,
        distance_from_target=row.distance,
        impact_reason=reason,
    )


def inheriting_class_row_to_impacted_symbol(
    row: InheritanceRow, *, target_qualified_name: str | None
) -> ImpactedSymbol:
    target_display = target_qualified_name or "the target class"
    if row.distance == 1:
        reason = f"Directly extends {target_display}; its own definitions may be affected."
    else:
        reason = f"Extends {target_display} through {row.distance} inheritance level(s)."
    return ImpactedSymbol(
        symbol_id=row.node.id,
        qualified_name=row.node.qualified_name,
        symbol_type=row.node.label.value,
        file_path=row.node.file_path,
        start_line=row.node.start_line,
        end_line=row.node.end_line,
        impact_type=ImpactType.INHERITING_CLASS,
        distance=row.distance,
        reason=reason,
        relationship_path=["EXTENDS"] * row.distance,
    )


_IMPACT_EVIDENCE_TYPE: dict[ImpactType, EvidenceType] = {
    ImpactType.DIRECT_CALLER: EvidenceType.CALL_RELATIONSHIP,
    ImpactType.TRANSITIVE_CALLER: EvidenceType.CALL_RELATIONSHIP,
    ImpactType.CALLEE: EvidenceType.CALL_RELATIONSHIP,
    ImpactType.DEPENDENCY: EvidenceType.DEPENDENCY_RELATIONSHIP,
    ImpactType.INHERITING_CLASS: EvidenceType.INHERITANCE_RELATIONSHIP,
    ImpactType.BASE_CLASS: EvidenceType.INHERITANCE_RELATIONSHIP,
    ImpactType.API_ENDPOINT: EvidenceType.API_ENDPOINT,
    ImpactType.TEST_REFERENCE: EvidenceType.CALL_RELATIONSHIP,
}


def impact_summary_text(result: ImpactAnalysisResult) -> str:
    """A short, plain-language framing of the deterministic result — fed
    to the LLM as one evidence item (see impact_result_to_evidence) so
    the natural-language pipeline can reference risk score/level and
    counts without any extra prompt-builder changes."""
    target_name = result.target.qualified_name or result.target.name
    lines = [
        f"Deterministic change-impact analysis for {target_name} "
        f"({result.target.target_type.value}):",
        f"- Risk score: {result.risk_score:.1f}/100 ({result.risk_level.value}) — a structural "
        "heuristic, not a probability of failure.",
        f"- {len(result.direct_callers)} direct caller(s), "
        f"{len(result.transitive_dependents)} transitive dependent(s).",
        f"- {len(result.affected_endpoints)} API endpoint(s) potentially affected.",
        f"- {len(result.affected_files)} file(s) and {len(result.affected_modules)} module(s) "
        "potentially affected.",
        f"- {len(result.downstream_dependencies)} downstream dependency(ies) the target itself "
        "calls.",
        f"- {len(result.inheritance_impacts)} inheritance-related impact(s).",
        f"- Test relationship: {result.test_relationship_status.value}.",
    ]
    if result.truncated:
        lines.append("- NOTE: traversal was truncated at the configured depth/node/path limit.")
    return "\n".join(lines)


def impact_result_to_evidence(result: ImpactAnalysisResult) -> list[RetrievalEvidence]:
    """A summary item (always first/most relevant) plus one evidence item
    per impacted symbol that has a real file location — endpoints are
    intentionally excluded here since ``ImpactedEndpoint`` carries no
    file/line of its own (see the impact-analysis task's own endpoint
    model, which has no location field)."""
    evidence = [
        RetrievalEvidence(
            id=f"impact-summary:{result.target.symbol_id}",
            repository_id=result.repository_id,
            evidence_type=EvidenceType.GRAPH_STATISTIC,
            symbol_id=result.target.symbol_id,
            qualified_name=result.target.qualified_name,
            file_path=result.target.file_path,
            start_line=result.target.start_line,
            end_line=result.target.end_line,
            content=impact_summary_text(result),
            source=EvidenceSource.GRAPH,
            metadata={"impact_role": "summary"},
        )
    ]
    all_symbols = (
        result.direct_callers
        + result.transitive_dependents
        + result.downstream_dependencies
        + result.inheritance_impacts
    )
    for symbol in all_symbols:
        if symbol.file_path is None:
            continue
        evidence.append(
            RetrievalEvidence(
                id=f"impact:{symbol.symbol_id}:{symbol.impact_type.value}:{symbol.distance}",
                repository_id=result.repository_id,
                evidence_type=_IMPACT_EVIDENCE_TYPE.get(symbol.impact_type, EvidenceType.SYMBOL),
                symbol_id=symbol.symbol_id,
                qualified_name=symbol.qualified_name,
                file_path=symbol.file_path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                content=symbol.reason,
                source=EvidenceSource.GRAPH,
                graph_distance=symbol.distance,
                relationship_type=(
                    symbol.relationship_path[-1] if symbol.relationship_path else None
                ),
                metadata={"impact_type": symbol.impact_type.value},
            )
        )
    return evidence


def base_class_row_to_impacted_symbol(
    row: InheritanceRow, *, target_qualified_name: str | None
) -> ImpactedSymbol:
    target_display = target_qualified_name or "the target class"
    reason = f"{target_display} extends this class (directly or transitively)."
    return ImpactedSymbol(
        symbol_id=row.node.id,
        qualified_name=row.node.qualified_name,
        symbol_type=row.node.label.value,
        file_path=row.node.file_path,
        start_line=row.node.start_line,
        end_line=row.node.end_line,
        impact_type=ImpactType.BASE_CLASS,
        distance=row.distance,
        reason=reason,
        relationship_path=["EXTENDS"] * row.distance,
    )

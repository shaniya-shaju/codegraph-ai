"""Request-level orchestration for change-impact analysis: target
resolution (symbol_id preferred, qualified_name via the existing
SymbolRetriever with ambiguity handling) + target-type validation, then
delegates the actual traversal/scoring to ``app.impact.analyzer`` — see
"Symbol resolution": "Symbol ID should be preferred because it is
unambiguous." / "never choose randomly between multiple matches."

This is the only module ``app.api.routes.impact`` calls directly for the
deterministic endpoint.
"""

from app.core.config import Settings
from app.domain.graph.models import GraphNode
from app.domain.impact.enums import ImpactTargetType
from app.domain.impact.models import ImpactAnalysisResult
from app.domain.rag.enums import SymbolResolutionStatus
from app.graph import repository_graph_service
from app.graph.neo4j_client import Neo4jClient
from app.impact import mappers
from app.impact.analyzer import analyze_impact
from app.impact.exceptions import (
    AmbiguousTargetError,
    InvalidImpactParameterError,
    TargetSymbolNotFoundError,
    UnsupportedTargetTypeError,
)
from app.rag.symbol_retriever import SymbolRetriever


def resolve_target(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str | None,
    qualified_name: str | None,
) -> GraphNode:
    if symbol_id:
        node = repository_graph_service.get_symbol(
            client, repository_id=repository_id, symbol_id=symbol_id
        )
        if node is None:
            raise TargetSymbolNotFoundError(f"No symbol with id {symbol_id!r} exists.")
        return node

    if qualified_name:
        resolution = SymbolRetriever(client, settings).resolve(
            repository_id=repository_id, query=qualified_name
        )
        if resolution.status is SymbolResolutionStatus.NOT_FOUND:
            raise TargetSymbolNotFoundError(f"No symbol matching {qualified_name!r} was found.")
        if resolution.status is SymbolResolutionStatus.AMBIGUOUS:
            candidate_names = [c.qualified_name or c.name for c in resolution.candidates]
            raise AmbiguousTargetError(
                f"The symbol {qualified_name!r} matches multiple candidates; specify a "
                "symbol_id instead.",
                candidates=candidate_names,
            )
        resolved = resolution.resolved_symbol
        assert resolved is not None  # EXACT/UNIQUE always carries a resolved symbol
        return GraphNode(
            id=resolved.symbol_id,
            repository_id=repository_id,
            label=resolved.symbol_type,
            name=resolved.name,
            qualified_name=resolved.qualified_name,
            file_path=resolved.file_path,
            start_line=resolved.start_line,
            end_line=resolved.end_line,
        )

    raise InvalidImpactParameterError("Either symbol_id or qualified_name must be provided.")


def get_impact_analysis(
    client: Neo4jClient,
    settings: Settings,
    *,
    repository_id: str,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    max_depth: int | None = None,
    max_nodes: int | None = None,
    include_downstream: bool = True,
    include_tests: bool = True,
) -> ImpactAnalysisResult:
    target_node = resolve_target(
        client,
        settings,
        repository_id=repository_id,
        symbol_id=symbol_id,
        qualified_name=qualified_name,
    )
    target_type = mappers.target_type_for_label(target_node.label)
    if target_type is None:
        raise UnsupportedTargetTypeError(
            f"{target_node.label.value} does not have defined change-impact semantics; "
            f"supported types are {', '.join(t.value for t in ImpactTargetType)}."
        )
    return analyze_impact(
        client,
        settings,
        repository_id=repository_id,
        target_node=target_node,
        target_type=target_type,
        max_depth=max_depth,
        max_nodes=max_nodes,
        include_downstream=include_downstream,
        include_tests=include_tests,
    )

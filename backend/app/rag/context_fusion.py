"""Explainable hybrid ranking — see "Context-fusion ranking" / "Intent
relevance". Every score is a deterministic function of the evidence, the
query intent, and configured weights; components are always returned
alongside the final score for debugging (never hidden inside one opaque
number).
"""

from app.core.config import Settings
from app.domain.rag.enums import EvidenceType, QueryIntent, SymbolResolutionStatus
from app.domain.rag.models import (
    RankedEvidence,
    RetrievalEvidence,
    ScoreComponents,
    SymbolResolution,
)
from app.rag.evidence import DeduplicatedEvidence


def _graph_proximity_score(distance: int | None) -> float:
    """1.0 at distance 0, 0.5 at distance 1, decaying thereafter. ``None``
    (an unknown/unmeasured hop count — see graph_retriever.py) scores 0.0
    rather than guessing."""
    if distance is None:
        return 0.0
    return 1.0 / (1 + max(distance, 0))


def _intent_relevance(
    item: RetrievalEvidence, *, intent: QueryIntent, exact_symbol_ids: frozenset[str]
) -> float:
    """See "Intent relevance" — deterministic, per-intent rules. Falls
    back to a neutral 0.5 for intents/evidence combinations with no
    special-cased rule."""
    operation = item.metadata.get("graph_operation")

    if intent == QueryIntent.CALLER_LOOKUP:
        return 1.0 if item.relationship_type == "CALLS" and operation == "callers" else 0.3
    if intent == QueryIntent.CALLEE_LOOKUP:
        return 1.0 if item.relationship_type == "CALLS" and operation == "callees" else 0.3
    if intent == QueryIntent.DEPENDENCY_LOOKUP:
        return 1.0 if operation == "dependencies" else 0.3
    if intent == QueryIntent.INHERITANCE_LOOKUP:
        return 1.0 if operation == "inheritance" or item.relationship_type == "EXTENDS" else 0.3
    if intent == QueryIntent.IMPACT_ANALYSIS:
        if operation in ("callers", "dependencies"):
            return 1.0
        if operation == "neighbors":
            return 0.6
        return 0.4
    if intent == QueryIntent.ARCHITECTURE:
        if item.evidence_type in (EvidenceType.MODULE, EvidenceType.GRAPH_STATISTIC):
            return 1.0
        if item.evidence_type == EvidenceType.DEPENDENCY_RELATIONSHIP:
            return 0.8
        if (
            item.evidence_type == EvidenceType.CODE_CHUNK
            and item.metadata.get("chunk_type") == "class"
        ):
            return 0.8
        return 0.4
    if intent == QueryIntent.CODE_EXPLANATION:
        if item.symbol_id is not None and item.symbol_id in exact_symbol_ids:
            return 1.0
        if operation == "neighbors" or item.relationship_type == "CALLS":
            return 0.6
        return 0.3
    if intent == QueryIntent.API_LOOKUP:
        return (
            1.0
            if item.evidence_type == EvidenceType.API_ENDPOINT or operation == "api_handler"
            else 0.4
        )
    if intent == QueryIntent.CODE_LOCATION:
        return 0.9 if item.symbol_id is not None and item.symbol_id in exact_symbol_ids else 0.5
    return 0.5


def _exact_symbol_ids(resolved_symbols: list[SymbolResolution]) -> frozenset[str]:
    return frozenset(
        r.resolved_symbol.symbol_id
        for r in resolved_symbols
        if r.resolved_symbol is not None
        and r.status in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE)
    )


def rank_evidence(
    deduped: list[DeduplicatedEvidence],
    *,
    analysis_intent: QueryIntent,
    resolved_symbols: list[SymbolResolution],
    settings: Settings,
) -> list[RankedEvidence]:
    exact_symbol_ids = _exact_symbol_ids(resolved_symbols)
    ranked: list[RankedEvidence] = []

    for item in deduped:
        vector_component = item.vector_score if item.vector_score is not None else 0.0
        exact_component = (
            item.exact_match_score
            if item.exact_match_score is not None
            else (1.0 if item.evidence.symbol_id in exact_symbol_ids else 0.0)
        )
        graph_component = _graph_proximity_score(item.graph_distance)
        intent_component = _intent_relevance(
            item.evidence, intent=analysis_intent, exact_symbol_ids=exact_symbol_ids
        )

        hybrid_score = (
            settings.hybrid_vector_weight * vector_component
            + settings.hybrid_exact_weight * exact_component
            + settings.hybrid_graph_weight * graph_component
            + settings.hybrid_intent_weight * intent_component
        )

        ranked.append(
            RankedEvidence(
                evidence=item.evidence,
                hybrid_score=hybrid_score,
                score_components=ScoreComponents(
                    vector=vector_component,
                    exact=exact_component,
                    graph=graph_component,
                    intent=intent_component,
                ),
                sources=item.sources,
            )
        )

    ranked.sort(key=lambda r: r.hybrid_score, reverse=True)
    return ranked

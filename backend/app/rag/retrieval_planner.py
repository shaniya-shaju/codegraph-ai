"""Deterministic retrieval planning — see "Retrieval planning".

Every rule here is a plain, testable mapping from ``QueryIntent`` to which
retrieval components run and how deep/wide they're allowed to go. No
LLM involvement (planning is a pure function of the analysis + configured
bounds).
"""

from app.core.config import Settings
from app.domain.rag.enums import GraphRetrievalOperation, QueryIntent
from app.domain.rag.models import QueryAnalysis, RetrievalPlan


def _clamp_depth(depth: int | None, *, default: int, maximum: int) -> int:
    value = depth if depth is not None else default
    return max(1, min(value, maximum))


def build_retrieval_plan(analysis: QueryAnalysis, *, settings: Settings) -> RetrievalPlan:
    intent = analysis.primary_intent
    symbol_limit = settings.rag_symbol_candidate_limit
    default_depth = settings.graph_default_traversal_depth
    max_depth = settings.graph_max_traversal_depth
    vector_top_k = settings.vector_default_top_k

    if intent == QueryIntent.CODE_LOCATION:
        # Semantic search first, exact-symbol support, a little graph
        # context around whatever gets resolved.
        return RetrievalPlan(
            use_vector=True,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=_clamp_depth(analysis.requested_depth, default=1, maximum=max_depth),
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.NEIGHBORS],
        )

    if intent == QueryIntent.CODE_EXPLANATION:
        return RetrievalPlan(
            use_vector=True,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=_clamp_depth(analysis.requested_depth, default=1, maximum=max_depth),
            symbol_limit=symbol_limit,
            graph_operations=[
                GraphRetrievalOperation.SYMBOL_DETAILS,
                GraphRetrievalOperation.NEIGHBORS,
            ],
        )

    if intent == QueryIntent.CALLER_LOOKUP:
        return RetrievalPlan(
            use_vector=False,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=1,
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.CALLERS],
        )

    if intent == QueryIntent.CALLEE_LOOKUP:
        return RetrievalPlan(
            use_vector=False,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=1,
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.CALLEES],
        )

    if intent == QueryIntent.DEPENDENCY_LOOKUP:
        return RetrievalPlan(
            use_vector=False,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=_clamp_depth(
                analysis.requested_depth, default=default_depth, maximum=max_depth
            ),
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.DEPENDENCIES],
        )

    if intent == QueryIntent.IMPACT_ANALYSIS:
        # Structural evidence only at this stage — see the task's "DO NOT
        # calculate final impact risk yet."
        return RetrievalPlan(
            use_vector=False,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=_clamp_depth(
                analysis.requested_depth,
                default=settings.impact_analysis_default_max_depth,
                maximum=max_depth,
            ),
            symbol_limit=symbol_limit,
            graph_operations=[
                GraphRetrievalOperation.CALLERS,
                GraphRetrievalOperation.DEPENDENCIES,
                GraphRetrievalOperation.NEIGHBORS,
            ],
        )

    if intent == QueryIntent.INHERITANCE_LOOKUP:
        return RetrievalPlan(
            use_vector=False,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=1,
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.INHERITANCE],
        )

    if intent == QueryIntent.API_LOOKUP:
        return RetrievalPlan(
            use_vector=True,
            use_graph=True,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=1,
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.API_HANDLER],
        )

    if intent == QueryIntent.ARCHITECTURE:
        return RetrievalPlan(
            use_vector=True,
            use_graph=True,
            use_symbol_search=False,
            vector_top_k=min(vector_top_k * 2, settings.vector_max_top_k),
            graph_depth=_clamp_depth(
                analysis.requested_depth, default=default_depth, maximum=max_depth
            ),
            symbol_limit=symbol_limit,
            graph_operations=[GraphRetrievalOperation.REPOSITORY_OVERVIEW],
        )

    if intent == QueryIntent.GENERAL_CODE_QUESTION:
        return RetrievalPlan(
            use_vector=True,
            use_graph=False,
            use_symbol_search=True,
            vector_top_k=vector_top_k,
            graph_depth=default_depth,
            symbol_limit=symbol_limit,
            graph_operations=[],
        )

    # UNKNOWN: best-effort minimal plan.
    return RetrievalPlan(
        use_vector=True,
        use_graph=False,
        use_symbol_search=False,
        vector_top_k=vector_top_k,
        graph_depth=default_depth,
        symbol_limit=symbol_limit,
        graph_operations=[],
    )

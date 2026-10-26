"""The top-level orchestrator — see "Architectural objective" for the
full pipeline this implements:

question -> query analysis -> retrieval planning -> (vector / exact
symbol / graph retrieval) -> evidence normalization -> deduplication ->
context fusion/ranking -> token/character budgeting -> HybridRetrievalResult.

Deliberately does not generate a natural-language answer (see the task's
"DO NOT generate the final natural-language answer in this stage.").
"""

import dataclasses
import logging
import time

from app.core.config import Settings
from app.domain.rag.enums import (
    EvidenceSource,
    EvidenceType,
    GraphRetrievalOperation,
    RetrievalMode,
    SymbolResolutionStatus,
)
from app.domain.rag.models import (
    HybridRetrievalResult,
    QueryAnalysis,
    RetrievalDiagnostics,
    RetrievalEvidence,
    RetrievalPlan,
    SymbolResolution,
)
from app.graph.exceptions import GraphError
from app.graph.neo4j_client import Neo4jClient
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.exceptions import VectorStoreError
from app.indexing.vector_store import VectorStore
from app.rag.context_budget import apply_budget
from app.rag.context_fusion import rank_evidence
from app.rag.evidence import deduplicate_evidence
from app.rag.graph_retriever import GraphRetriever
from app.rag.llm_provider import StructuredLLMProvider
from app.rag.query_analyzer import analyze_query
from app.rag.retrieval_planner import build_retrieval_plan
from app.rag.symbol_retriever import SymbolRetriever
from app.rag.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)


def _now_ms() -> float:
    return time.monotonic() * 1000


def _resolve_symbols(
    symbol_retriever: SymbolRetriever, *, repository_id: str, analysis: QueryAnalysis, limit: int
) -> tuple[list[SymbolResolution], str | None]:
    """Resolves every distinct mentioned entity, in order of specificity
    (qualified-looking strings first). Returns the resolutions plus the
    first confidently-resolved symbol_id (used as the "target symbol" for
    single-symbol graph operations like CALLERS/CALLEES)."""
    candidates = list(
        dict.fromkeys([*analysis.symbols, *analysis.function_names, *analysis.class_names])
    )
    hint_file_paths = frozenset(analysis.file_paths)

    resolutions: list[SymbolResolution] = []
    target_symbol_id: str | None = None
    for query in candidates:
        resolution = symbol_retriever.resolve(
            repository_id=repository_id, query=query, hint_file_paths=hint_file_paths, limit=limit
        )
        resolutions.append(resolution)
        if (
            target_symbol_id is None
            and resolution.status in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE)
            and resolution.resolved_symbol is not None
        ):
            target_symbol_id = resolution.resolved_symbol.symbol_id
    return resolutions, target_symbol_id


def _symbol_evidence(
    resolutions: list[SymbolResolution], *, repository_id: str
) -> list[RetrievalEvidence]:
    """A confidently-resolved symbol is itself evidence (source=SYMBOL,
    exact_match_score reflecting resolution confidence) — separate from
    whatever SYMBOL_DETAILS/graph evidence may also describe it."""
    evidence: list[RetrievalEvidence] = []
    for resolution in resolutions:
        symbol = resolution.resolved_symbol
        if symbol is None:
            continue
        location = (
            f"{symbol.file_path}:{symbol.start_line}-{symbol.end_line}"
            if symbol.file_path
            else "unknown location"
        )
        display_name = symbol.qualified_name or symbol.name
        content = f"{symbol.symbol_type.value} {display_name} ({location})"
        evidence.append(
            RetrievalEvidence(
                id=f"symbol:{symbol.symbol_id}",
                repository_id=repository_id,
                evidence_type=EvidenceType.SYMBOL,
                symbol_id=symbol.symbol_id,
                qualified_name=symbol.qualified_name,
                file_path=symbol.file_path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                content=content,
                source=EvidenceSource.SYMBOL,
                exact_match_score=symbol.confidence,
                metadata={
                    "resolved_from_query": resolution.query,
                    "resolution_status": resolution.status.value,
                },
            )
        )
    return evidence


def _run_graph_operations(
    graph_retriever: GraphRetriever,
    plan: RetrievalPlan,
    *,
    repository_id: str,
    target_symbol_id: str | None,
    analysis: QueryAnalysis,
) -> list[RetrievalEvidence]:
    evidence: list[RetrievalEvidence] = []
    query_for_api = analysis.api_routes[0] if analysis.api_routes else analysis.raw_question
    for operation in plan.graph_operations:
        if operation == GraphRetrievalOperation.API_HANDLER:
            evidence.extend(
                graph_retriever.run(
                    operation,
                    repository_id=repository_id,
                    query=query_for_api,
                    limit=plan.symbol_limit,
                )
            )
            continue
        if operation == GraphRetrievalOperation.REPOSITORY_OVERVIEW:
            evidence.extend(
                graph_retriever.run(operation, repository_id=repository_id, depth=plan.graph_depth)
            )
            continue
        if target_symbol_id is None:
            continue  # every other operation needs a resolved symbol
        evidence.extend(
            graph_retriever.run(
                operation,
                repository_id=repository_id,
                symbol_id=target_symbol_id,
                depth=plan.graph_depth,
            )
        )
    return evidence


def _apply_mode_override(plan: RetrievalPlan, mode: RetrievalMode) -> RetrievalPlan:
    """Vector/graph modes must be independently evaluable (see the task's
    "Evaluation readiness": "Do not hardwire hybrid retrieval so deeply
    that vector-only cannot be evaluated independently") — VECTOR mode
    turns off symbol search too, not just graph operations, since symbol
    resolution exists to feed graph lookups.

    Must force its own mode's flag *on*, not just suppress the others —
    the intent-derived plan (see retrieval_planner.py) sets use_vector to
    False by default for several intents (CALLER_LOOKUP, CALLEE_LOOKUP,
    DEPENDENCY_LOOKUP, IMPACT_ANALYSIS, INHERITANCE_LOOKUP). Without the
    explicit override below, requesting mode=VECTOR while the analyzer
    happens to classify the question into one of those intents produced
    a plan with every flag False and silently returned no evidence at
    all — exactly defeating the "independently evaluable" guarantee this
    docstring describes."""
    if mode == RetrievalMode.VECTOR:
        return dataclasses.replace(
            plan, use_vector=True, use_graph=False, use_symbol_search=False, graph_operations=[]
        )
    if mode == RetrievalMode.GRAPH:
        return dataclasses.replace(plan, use_vector=False, use_graph=True)
    return plan


async def retrieve(
    *,
    repository_id: str,
    question: str,
    mode: RetrievalMode = RetrievalMode.HYBRID,
    top_k: int | None,
    settings: Settings,
    neo4j_client: Neo4jClient,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    llm_provider: StructuredLLMProvider | None = None,
) -> HybridRetrievalResult:
    started = _now_ms()
    warnings: list[str] = []
    fallbacks_used: list[str] = []

    analysis_start = _now_ms()
    analysis = await analyze_query(question, settings=settings, llm_provider=llm_provider)
    analysis_ms = int(_now_ms() - analysis_start)
    if analysis.analysis_strategy == "llm_fallback_heuristic":
        fallbacks_used.append("llm_query_analysis_failed_used_heuristic")

    plan = _apply_mode_override(build_retrieval_plan(analysis, settings=settings), mode)

    resolved_symbols: list[SymbolResolution] = []
    target_symbol_id: str | None = None
    if plan.use_symbol_search or plan.use_graph:
        symbol_retriever = SymbolRetriever(neo4j_client, settings)
        try:
            resolved_symbols, target_symbol_id = _resolve_symbols(
                symbol_retriever,
                repository_id=repository_id,
                analysis=analysis,
                limit=plan.symbol_limit,
            )
        except GraphError as exc:
            warnings.append(f"symbol resolution failed: {exc}")
            fallbacks_used.append("symbol_resolution_failed")

    vector_evidence: list[RetrievalEvidence] = []
    vector_ms = 0
    if plan.use_vector:
        vector_start = _now_ms()
        try:
            vector_retriever = VectorRetriever(embedding_provider, vector_store, settings)
            vector_evidence = vector_retriever.run(
                repository_id=repository_id, query=question, top_k=top_k or plan.vector_top_k
            )
        except VectorStoreError as exc:
            warnings.append(f"vector retrieval failed: {exc}")
            fallbacks_used.append("vector_retrieval_failed")
        vector_ms = int(_now_ms() - vector_start)

    graph_evidence: list[RetrievalEvidence] = []
    graph_ms = 0
    if plan.use_graph:
        graph_start = _now_ms()
        try:
            graph_retriever = GraphRetriever(neo4j_client, settings)
            graph_evidence = _run_graph_operations(
                graph_retriever,
                plan,
                repository_id=repository_id,
                target_symbol_id=target_symbol_id,
                analysis=analysis,
            )
        except GraphError as exc:
            warnings.append(f"graph retrieval failed: {exc}")
            fallbacks_used.append("graph_retrieval_failed")
        graph_ms = int(_now_ms() - graph_start)

    symbol_evidence = _symbol_evidence(resolved_symbols, repository_id=repository_id)

    all_evidence = vector_evidence + graph_evidence + symbol_evidence
    deduped = deduplicate_evidence(all_evidence)
    ranked = rank_evidence(
        deduped,
        analysis_intent=analysis.primary_intent,
        resolved_symbols=resolved_symbols,
        settings=settings,
    )
    budgeted, truncated = apply_budget(ranked, settings=settings)

    total_ms = int(_now_ms() - started)
    diagnostics = RetrievalDiagnostics(
        retrieval_duration_ms=total_ms,
        vector_duration_ms=vector_ms,
        graph_duration_ms=graph_ms,
        analysis_duration_ms=analysis_ms,
        fallbacks_used=fallbacks_used,
        warnings=warnings,
    )

    return HybridRetrievalResult(
        repository_id=repository_id,
        question=question,
        analysis=analysis,
        plan=plan,
        resolved_symbols=resolved_symbols,
        evidence=budgeted,
        total_vector_candidates=len(vector_evidence),
        total_graph_candidates=len(graph_evidence),
        total_symbol_candidates=len(symbol_evidence),
        deduplicated_count=len(deduped),
        returned_count=len(budgeted),
        truncated=truncated,
        diagnostics=diagnostics,
    )

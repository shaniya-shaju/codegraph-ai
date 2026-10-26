"""The top-level grounded-answer orchestrator — see the answer-
generation task's core pipeline:

question -> hybrid retrieval -> evidence selection -> grounded prompt
builder -> LLM generation -> structured answer parsing -> citation
validation -> grounding validation -> CodeAnswer.

This is the only module api/routes/query.py calls directly.
"""

import dataclasses
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.rag.enums import EvidenceSource, QueryIntent, RetrievalMode
from app.domain.rag.models import (
    HybridRetrievalResult,
    RankedEvidence,
    ScoreComponents,
    SymbolResolution,
)
from app.graph.exceptions import GraphError, Neo4jConnectionError
from app.graph.neo4j_client import Neo4jClient
from app.impact import mappers as impact_mappers
from app.impact import service as impact_service
from app.impact.exceptions import ImpactError
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.vector_store import VectorStore
from app.rag.answer_generator import (
    GeneratedAnswer,
    generate_answer,
    parse_streamed_text,
    stream_answer_text,
)
from app.rag.answer_models import (
    AnswerConfidence,
    AnswerDiagnostics,
    CodeAnswer,
    ResolvedSymbolReference,
)
from app.rag.citation_builder import EvidencePoolItem, build_evidence_pool, format_evidence_block
from app.rag.citation_validator import CitationValidationResult, validate_and_build_citations
from app.rag.conversation_context import (
    ConversationRole,
    append_turn,
    get_conversation_repository_id,
    get_recent_turns,
    resolve_follow_up_question,
)
from app.rag.exceptions import ConversationRepositoryMismatchError, LLMAnalysisError
from app.rag.grounding_validator import (
    AbstentionDecision,
    check_post_generation,
    check_pre_generation,
    classify_confidence,
)
from app.rag.hybrid_retriever import retrieve
from app.rag.llm_provider import AnswerLLMProvider, StructuredLLMProvider


def _to_resolved_symbol_reference(resolution: SymbolResolution) -> ResolvedSymbolReference:
    symbol = resolution.resolved_symbol
    return ResolvedSymbolReference(
        query=resolution.query,
        qualified_name=symbol.qualified_name if symbol else None,
        symbol_id=symbol.symbol_id if symbol else None,
        file_path=symbol.file_path if symbol else None,
        start_line=symbol.start_line if symbol else None,
        end_line=symbol.end_line if symbol else None,
        status=resolution.status,
    )


def _build_abstained_answer(
    retrieval_result: HybridRetrievalResult,
    decision: AbstentionDecision,
    *,
    retrieval_mode: RetrievalMode,
    retrieval_ms: int,
    generation_ms: int,
    started: float,
    extra_warning: str | None = None,
) -> CodeAnswer:
    total_ms = int((time.monotonic() - started) * 1000)
    warnings = [extra_warning] if extra_warning else []
    return CodeAnswer(
        repository_id=retrieval_result.repository_id,
        question=retrieval_result.question,
        answer=decision.message
        or "I could not find enough repository evidence to determine this reliably.",
        citations=[],
        confidence_level=AnswerConfidence.INSUFFICIENT_EVIDENCE,
        confidence_reason=decision.reason or "insufficient_evidence",
        retrieval_mode=retrieval_mode.value,
        primary_intent=retrieval_result.analysis.primary_intent.value,
        resolved_symbols=[
            _to_resolved_symbol_reference(r) for r in retrieval_result.resolved_symbols
        ],
        limitations=_degradation_limitations(retrieval_result),
        abstained=True,
        diagnostics=AnswerDiagnostics(
            retrieval_duration_ms=retrieval_ms,
            generation_duration_ms=generation_ms,
            total_duration_ms=total_ms,
            evidence_considered=len(retrieval_result.evidence),
            citations_returned=0,
            warnings=warnings,
        ),
    )


def _record_conversation(
    session: Session,
    *,
    conversation_id: str | None,
    repository_id: str,
    question: str,
    answer_text: str,
    referenced_qualified_name: str | None,
) -> None:
    if conversation_id is None:
        return
    append_turn(
        session,
        conversation_id=conversation_id,
        repository_id=repository_id,
        role=ConversationRole.USER,
        message=question,
    )
    append_turn(
        session,
        conversation_id=conversation_id,
        repository_id=repository_id,
        role=ConversationRole.ASSISTANT,
        message=answer_text,
        referenced_qualified_name=referenced_qualified_name,
    )


@dataclass(frozen=True)
class _EffectiveQuestion:
    text: str
    original: str


def _resolve_effective_question(
    session: Session,
    *,
    question: str,
    conversation_id: str | None,
    repository_id: str,
    settings: Settings,
) -> _EffectiveQuestion:
    if conversation_id is None:
        return _EffectiveQuestion(text=question, original=question)

    existing_repository_id = get_conversation_repository_id(session, conversation_id)
    if existing_repository_id is not None and existing_repository_id != repository_id:
        raise ConversationRepositoryMismatchError(
            f"conversation_id {conversation_id} belongs to a different repository."
        )

    recent_turns = get_recent_turns(
        session,
        conversation_id=conversation_id,
        repository_id=repository_id,
        limit=settings.conversation_max_turns,
    )
    return _EffectiveQuestion(
        text=resolve_follow_up_question(question, recent_turns), original=question
    )


def _select_impact_target(retrieval_result: HybridRetrievalResult) -> SymbolResolution | None:
    """The first confidently resolved symbol (EXACT/UNIQUE, never
    AMBIGUOUS) whose type has defined change-impact semantics — see
    app.impact.mappers.target_type_for_label. Returns None whenever a
    clean deterministic target can't be established, so the caller falls
    back to ordinary hybrid-retrieval evidence instead."""
    from app.domain.rag.enums import SymbolResolutionStatus

    for resolution in retrieval_result.resolved_symbols:
        symbol = resolution.resolved_symbol
        if symbol is None:
            continue
        if resolution.status not in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE):
            continue
        if impact_mappers.target_type_for_label(symbol.symbol_type) is None:
            continue
        return resolution
    return None


def _impact_evidence_to_ranked(evidence: list[object]) -> list[RankedEvidence]:
    ranked = []
    for i, ev in enumerate(evidence):
        distance = getattr(ev, "graph_distance", None) or 0
        # The summary item (always first) stays top-ranked; the rest
        # decay gently by graph distance so closer impact is cited first
        # — these are heuristic ranking scores, not probabilities (same
        # rule as app.rag.context_fusion).
        score = 1.0 if i == 0 else max(0.35, 1.0 - 0.12 * distance)
        ranked.append(
            RankedEvidence(
                evidence=ev,  # type: ignore[arg-type]
                hybrid_score=score,
                score_components=ScoreComponents(vector=0.0, exact=0.0, graph=score, intent=0.0),
                sources=[EvidenceSource.GRAPH],
            )
        )
    return ranked


def _try_impact_evidence(
    retrieval_result: HybridRetrievalResult,
    *,
    settings: Settings,
    neo4j_client: Neo4jClient,
) -> HybridRetrievalResult | None:
    """See "Natural-language integration": "the answer pipeline may call
    the deterministic impact service after resolving the symbol." When
    the question's primary intent is IMPACT_ANALYSIS and a symbol was
    confidently resolved to a supported target type, runs the
    deterministic engine and returns a copy of ``retrieval_result`` whose
    evidence is the impact result instead — the deterministic graph still
    decides what's affected; this only changes what gets shown to the
    LLM to explain. Returns None (no substitution) for any other
    question, or if the deterministic analysis itself fails for any
    reason, so ordinary questions and graph outages are never affected
    (see "Do not replace ordinary graph retrieval for unrelated
    questions.")."""
    if retrieval_result.analysis.primary_intent is not QueryIntent.IMPACT_ANALYSIS:
        return None
    resolution = _select_impact_target(retrieval_result)
    if resolution is None or resolution.resolved_symbol is None:
        return None

    try:
        impact_result = impact_service.get_impact_analysis(
            neo4j_client,
            settings,
            repository_id=retrieval_result.repository_id,
            symbol_id=resolution.resolved_symbol.symbol_id,
        )
    except (ImpactError, Neo4jConnectionError, GraphError):
        return None
    except Exception:  # noqa: BLE001 - this augmentation must never break Q&A
        logging.getLogger(__name__).warning(
            "Deterministic impact analysis failed unexpectedly during natural-language "
            "integration; falling back to ordinary retrieval evidence.",
            exc_info=True,
        )
        return None

    evidence = impact_mappers.impact_result_to_evidence(impact_result)
    ranked = _impact_evidence_to_ranked(list(evidence))
    return dataclasses.replace(
        retrieval_result,
        evidence=ranked,
        deduplicated_count=len(ranked),
        returned_count=len(ranked),
    )


async def answer_question(
    session: Session,
    *,
    repository_id: str,
    question: str,
    retrieval_mode: RetrievalMode,
    conversation_id: str | None,
    settings: Settings,
    neo4j_client: Neo4jClient,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    llm_provider: AnswerLLMProvider,
    query_analyzer_llm_provider: StructuredLLMProvider | None = None,
) -> CodeAnswer:
    started = time.monotonic()

    effective = _resolve_effective_question(
        session,
        question=question,
        conversation_id=conversation_id,
        repository_id=repository_id,
        settings=settings,
    )

    retrieval_start = time.monotonic()
    retrieval_result = await retrieve(
        repository_id=repository_id,
        question=effective.text,
        mode=retrieval_mode,
        top_k=None,
        settings=settings,
        neo4j_client=neo4j_client,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        llm_provider=query_analyzer_llm_provider,
    )
    retrieval_ms = int((time.monotonic() - retrieval_start) * 1000)

    impact_augmented = _try_impact_evidence(
        retrieval_result, settings=settings, neo4j_client=neo4j_client
    )
    if impact_augmented is not None:
        retrieval_result = impact_augmented

    pre_decision = check_pre_generation(retrieval_result, settings=settings)
    if pre_decision.should_abstain:
        answer = _build_abstained_answer(
            retrieval_result,
            pre_decision,
            retrieval_mode=retrieval_mode,
            retrieval_ms=retrieval_ms,
            generation_ms=0,
            started=started,
        )
        _record_conversation(
            session,
            conversation_id=conversation_id,
            repository_id=repository_id,
            question=effective.original,
            answer_text=answer.answer,
            referenced_qualified_name=None,
        )
        return answer

    pool = build_evidence_pool(retrieval_result.evidence, max_items=settings.answer_max_citations)
    evidence_block = format_evidence_block(pool)

    generation_start = time.monotonic()
    try:
        generated = await generate_answer(
            llm_provider,
            question=effective.text,
            evidence_block=evidence_block,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    except LLMAnalysisError as exc:
        generation_ms = int((time.monotonic() - generation_start) * 1000)
        decision = AbstentionDecision(
            True,
            "llm_generation_failed",
            "I could not generate a reliable answer right now — the language model request failed.",
        )
        answer = _build_abstained_answer(
            retrieval_result,
            decision,
            retrieval_mode=retrieval_mode,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started=started,
            extra_warning=str(exc),
        )
        _record_conversation(
            session,
            conversation_id=conversation_id,
            repository_id=repository_id,
            question=effective.original,
            answer_text=answer.answer,
            referenced_qualified_name=None,
        )
        return answer
    generation_ms = int((time.monotonic() - generation_start) * 1000)

    answer = _finalize_answer(
        retrieval_result,
        generated,
        pool=pool,
        retrieval_mode=retrieval_mode,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        started=started,
        settings=settings,
    )

    if answer.abstained:
        _record_conversation(
            session,
            conversation_id=conversation_id,
            repository_id=repository_id,
            question=effective.original,
            answer_text=answer.answer,
            referenced_qualified_name=None,
        )
    else:
        primary_ref = answer.resolved_symbols[0].qualified_name if answer.resolved_symbols else None
        _record_conversation(
            session,
            conversation_id=conversation_id,
            repository_id=repository_id,
            question=effective.original,
            answer_text=answer.answer,
            referenced_qualified_name=primary_ref,
        )
    return answer


_GRAPH_DEGRADED_MESSAGE = (
    "Knowledge-graph retrieval was unavailable for this question; this answer is based on "
    "vector evidence only."
)
_SYMBOL_RESOLUTION_DEGRADED_MESSAGE = (
    "Symbol resolution against the knowledge graph was unavailable for this question."
)


def _degradation_limitations(retrieval_result: HybridRetrievalResult) -> list[str]:
    """Translates the retrieval layer's internal fallback markers (see
    app.rag.hybrid_retriever's ``fallbacks_used`` — "graph_retrieval_failed"
    / "symbol_resolution_failed") into a plain-language limitation on the
    final answer — see the integration-reliability task's "Graceful
    degradation": "Do not silently pretend graph retrieval succeeded."
    The raw internal warning text (which may include exception details)
    is never surfaced directly; only this fixed, safe message is."""
    fallbacks = set(retrieval_result.diagnostics.fallbacks_used)
    notes = []
    if "graph_retrieval_failed" in fallbacks:
        notes.append(_GRAPH_DEGRADED_MESSAGE)
    if "symbol_resolution_failed" in fallbacks:
        notes.append(_SYMBOL_RESOLUTION_DEGRADED_MESSAGE)
    return notes


def _finalize_answer(
    retrieval_result: HybridRetrievalResult,
    generated: GeneratedAnswer,
    *,
    pool: list[EvidencePoolItem],
    retrieval_mode: RetrievalMode,
    retrieval_ms: int,
    generation_ms: int,
    started: float,
    settings: Settings,
) -> CodeAnswer:
    validation: CitationValidationResult = validate_and_build_citations(
        generated.raw_answer_text, pool
    )

    post_decision = check_post_generation(
        sufficient_evidence=generated.sufficient_evidence,
        had_citation_markers=generated.had_citation_markers,
        citations=validation.citations,
    )
    if post_decision.should_abstain:
        return _build_abstained_answer(
            retrieval_result,
            post_decision,
            retrieval_mode=retrieval_mode,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started=started,
        )

    top_score = retrieval_result.evidence[0].hybrid_score if retrieval_result.evidence else 0.0
    confidence_level, confidence_reason = classify_confidence(
        resolved_symbols=retrieval_result.resolved_symbols,
        citations=validation.citations,
        top_evidence_score=top_score,
        settings=settings,
    )

    limitations = list(generated.uncertainty_notes)
    limitations.extend(_degradation_limitations(retrieval_result))
    if validation.invalid_ids:
        limitations.append(
            f"The model referenced {len(validation.invalid_ids)} citation(s) that could not be "
            "verified against retrieved evidence; they were removed from the answer."
        )
    if validation.uncited_high_relevance_ids:
        limitations.append(
            "Some highly relevant retrieved evidence was not directly cited in this answer."
        )

    total_ms = int((time.monotonic() - started) * 1000)
    return CodeAnswer(
        repository_id=retrieval_result.repository_id,
        question=retrieval_result.question,
        answer=validation.answer_text,
        citations=validation.citations,
        confidence_level=confidence_level,
        confidence_reason=confidence_reason,
        retrieval_mode=retrieval_mode.value,
        primary_intent=retrieval_result.analysis.primary_intent.value,
        resolved_symbols=[
            _to_resolved_symbol_reference(r) for r in retrieval_result.resolved_symbols
        ],
        limitations=limitations,
        abstained=False,
        diagnostics=AnswerDiagnostics(
            retrieval_duration_ms=retrieval_ms,
            generation_duration_ms=generation_ms,
            total_duration_ms=total_ms,
            evidence_considered=len(pool),
            citations_returned=len(validation.citations),
            invalid_citation_ids=validation.invalid_ids,
        ),
    )


async def stream_answer(
    session: Session,
    *,
    repository_id: str,
    question: str,
    retrieval_mode: RetrievalMode,
    conversation_id: str | None,
    settings: Settings,
    neo4j_client: Neo4jClient,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    llm_provider: AnswerLLMProvider,
    query_analyzer_llm_provider: StructuredLLMProvider | None = None,
) -> AsyncIterator[dict[str, object]]:
    """Yields ``{"type": "chunk", "text": ...}`` events as raw generated
    text arrives, followed by exactly one ``{"type": "final", "answer":
    CodeAnswer}`` event once citations have been finalized/validated —
    see "Grounded citations must still be finalized and validated after
    generation." Never yields an unvalidated citation as final.
    """
    started = time.monotonic()
    effective = _resolve_effective_question(
        session,
        question=question,
        conversation_id=conversation_id,
        repository_id=repository_id,
        settings=settings,
    )

    retrieval_start = time.monotonic()
    retrieval_result = await retrieve(
        repository_id=repository_id,
        question=effective.text,
        mode=retrieval_mode,
        top_k=None,
        settings=settings,
        neo4j_client=neo4j_client,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        llm_provider=query_analyzer_llm_provider,
    )
    retrieval_ms = int((time.monotonic() - retrieval_start) * 1000)

    impact_augmented = _try_impact_evidence(
        retrieval_result, settings=settings, neo4j_client=neo4j_client
    )
    if impact_augmented is not None:
        retrieval_result = impact_augmented

    pre_decision = check_pre_generation(retrieval_result, settings=settings)
    if pre_decision.should_abstain:
        answer = _build_abstained_answer(
            retrieval_result,
            pre_decision,
            retrieval_mode=retrieval_mode,
            retrieval_ms=retrieval_ms,
            generation_ms=0,
            started=started,
        )
        yield {"type": "chunk", "text": answer.answer}
        yield {"type": "final", "answer": answer}
        _record_conversation(
            session,
            conversation_id=conversation_id,
            repository_id=repository_id,
            question=effective.original,
            answer_text=answer.answer,
            referenced_qualified_name=None,
        )
        return

    pool = build_evidence_pool(retrieval_result.evidence, max_items=settings.answer_max_citations)
    evidence_block = format_evidence_block(pool)

    generation_start = time.monotonic()
    collected: list[str] = []
    try:
        async for piece in stream_answer_text(
            llm_provider, question=effective.text, evidence_block=evidence_block
        ):
            collected.append(piece)
            yield {"type": "chunk", "text": piece}
    except LLMAnalysisError as exc:
        generation_ms = int((time.monotonic() - generation_start) * 1000)
        decision = AbstentionDecision(
            True,
            "llm_generation_failed",
            "I could not generate a reliable answer right now — the language model request failed.",
        )
        answer = _build_abstained_answer(
            retrieval_result,
            decision,
            retrieval_mode=retrieval_mode,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started=started,
            extra_warning=str(exc),
        )
        yield {"type": "final", "answer": answer}
        _record_conversation(
            session,
            conversation_id=conversation_id,
            repository_id=repository_id,
            question=effective.original,
            answer_text=answer.answer,
            referenced_qualified_name=None,
        )
        return
    generation_ms = int((time.monotonic() - generation_start) * 1000)

    generated = parse_streamed_text("".join(collected))
    answer = _finalize_answer(
        retrieval_result,
        generated,
        pool=pool,
        retrieval_mode=retrieval_mode,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        started=started,
        settings=settings,
    )
    yield {"type": "final", "answer": answer}

    primary_ref = (
        answer.resolved_symbols[0].qualified_name
        if not answer.abstained and answer.resolved_symbols
        else None
    )
    _record_conversation(
        session,
        conversation_id=conversation_id,
        repository_id=repository_id,
        question=effective.original,
        answer_text=answer.answer,
        referenced_qualified_name=primary_ref,
    )

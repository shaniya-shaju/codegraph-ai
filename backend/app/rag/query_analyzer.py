"""Combines the deterministic classifier/extractor with an optional LLM
strategy into one ``QueryAnalysis`` — see "Query analysis models" and
"LLM abstraction".

``QUERY_ANALYZER_MODE`` selects the strategy:

- ``heuristic``: deterministic only, never calls an LLM.
- ``llm``: LLM result is used directly (deterministic still runs first
  and is always the fallback on any LLM error).
- ``hybrid`` (default): deterministic runs first; if the LLM is enabled
  and available, its result is merged in conservatively.

An LLM outage/timeout/malformed-output never breaks retrieval — this
module always returns a usable ``QueryAnalysis``, falling back to the
deterministic result and recording that fact in ``analysis_strategy``.
"""

import dataclasses
import logging

from app.core.config import Settings
from app.domain.rag.enums import QueryAnalyzerMode, QueryIntent
from app.domain.rag.models import QueryAnalysis
from app.rag.entity_extractor import ExtractedEntities, extract_entities
from app.rag.exceptions import LLMAnalysisError
from app.rag.llm_provider import StructuredLLMProvider
from app.rag.prompts import QUERY_ANALYSIS_SYSTEM_PROMPT, build_query_analysis_user_prompt
from app.rag.query_classifier import ClassificationResult, classify_intent
from app.rag.structured_output import LLMQueryClassification

logger = logging.getLogger(__name__)

# Intents whose evidence is primarily structural (graph) rather than
# semantic (vector) — see "Retrieval planning".
_GRAPH_LED_INTENTS = frozenset(
    {
        QueryIntent.CALLER_LOOKUP,
        QueryIntent.CALLEE_LOOKUP,
        QueryIntent.DEPENDENCY_LOOKUP,
        QueryIntent.IMPACT_ANALYSIS,
        QueryIntent.INHERITANCE_LOOKUP,
        QueryIntent.API_LOOKUP,
        QueryIntent.ARCHITECTURE,
    }
)
_SYMBOL_LED_INTENTS = frozenset(
    {
        QueryIntent.CODE_LOCATION,
        QueryIntent.CODE_EXPLANATION,
        QueryIntent.CALLER_LOOKUP,
        QueryIntent.CALLEE_LOOKUP,
        QueryIntent.DEPENDENCY_LOOKUP,
        QueryIntent.IMPACT_ANALYSIS,
        QueryIntent.INHERITANCE_LOOKUP,
        QueryIntent.API_LOOKUP,
    }
)
# UNKNOWN gets no vector search (nothing sensible to embed-search for a
# question with zero code-relatedness signal).
_NO_VECTOR_INTENTS = frozenset({QueryIntent.UNKNOWN})


def _normalize(question: str) -> str:
    return " ".join(question.strip().lower().split())


def _requested_depth_from_text(question: str) -> int | None:
    import re

    match = re.search(r"\bdepth\s+(\d+)\b", question, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _deterministic_analysis(raw_question: str) -> QueryAnalysis:
    normalized = _normalize(raw_question)
    classification: ClassificationResult = classify_intent(normalized)
    entities: ExtractedEntities = extract_entities(raw_question)
    return _build_analysis(
        raw_question=raw_question,
        normalized_question=normalized,
        primary_intent=classification.primary_intent,
        secondary_intents=classification.secondary_intents,
        entities=entities,
        requested_depth=_requested_depth_from_text(raw_question),
        confidence=classification.confidence,
        analysis_strategy="heuristic",
    )


def _build_analysis(
    *,
    raw_question: str,
    normalized_question: str,
    primary_intent: QueryIntent,
    secondary_intents: list[QueryIntent],
    entities: ExtractedEntities,
    requested_depth: int | None,
    confidence: float | None,
    analysis_strategy: str,
) -> QueryAnalysis:
    return QueryAnalysis(
        raw_question=raw_question,
        normalized_question=normalized_question,
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        symbols=entities.symbols,
        file_paths=entities.file_paths,
        module_names=entities.module_names,
        class_names=entities.class_names,
        function_names=entities.function_names,
        api_routes=entities.api_routes,
        requested_depth=requested_depth,
        requires_vector_search=primary_intent not in _NO_VECTOR_INTENTS,
        requires_graph_search=primary_intent in _GRAPH_LED_INTENTS,
        requires_exact_symbol_search=primary_intent in _SYMBOL_LED_INTENTS,
        confidence=confidence,
        analysis_strategy=analysis_strategy,
    )


def _merge_conservatively(
    deterministic: QueryAnalysis, llm_result: LLMQueryClassification
) -> QueryAnalysis:
    """Conservative merge: the deterministic intent wins unless it was a
    low-confidence fallback (GENERAL_CODE_QUESTION/UNKNOWN), in which case
    a more specific LLM intent is allowed to take over. Extracted entities
    are always the union of both (deterministic first) — an LLM never
    *removes* something the deterministic pass already found."""
    primary_intent: QueryIntent
    confidence: float | None
    low_confidence_fallback = deterministic.primary_intent in (
        QueryIntent.GENERAL_CODE_QUESTION,
        QueryIntent.UNKNOWN,
    )
    if low_confidence_fallback and llm_result.primary_intent != QueryIntent.UNKNOWN:
        primary_intent = llm_result.primary_intent
        secondary_intents = [
            *deterministic.secondary_intents,
            *[i for i in llm_result.secondary_intents if i != primary_intent],
        ]
        confidence = llm_result.confidence
    else:
        primary_intent = deterministic.primary_intent
        secondary_intents = [
            *deterministic.secondary_intents,
            *[
                i
                for i in [llm_result.primary_intent, *llm_result.secondary_intents]
                if i != primary_intent and i not in deterministic.secondary_intents
            ],
        ]
        confidence = deterministic.confidence

    def _union(a: list[str], b: list[str]) -> list[str]:
        seen = {v.lower() for v in a}
        return a + [v for v in b if v.lower() not in seen]

    return dataclasses.replace(
        deterministic,
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        symbols=_union(deterministic.symbols, llm_result.symbols),
        file_paths=_union(deterministic.file_paths, llm_result.file_paths),
        module_names=_union(deterministic.module_names, llm_result.module_names),
        class_names=_union(deterministic.class_names, llm_result.class_names),
        function_names=_union(deterministic.function_names, llm_result.function_names),
        api_routes=_union(deterministic.api_routes, llm_result.api_routes),
        requested_depth=deterministic.requested_depth or llm_result.requested_depth,
        requires_vector_search=primary_intent not in _NO_VECTOR_INTENTS,
        requires_graph_search=primary_intent in _GRAPH_LED_INTENTS,
        requires_exact_symbol_search=primary_intent in _SYMBOL_LED_INTENTS,
        confidence=confidence,
        analysis_strategy="hybrid_merged",
    )


async def analyze_query(
    raw_question: str,
    *,
    settings: Settings,
    llm_provider: StructuredLLMProvider | None,
) -> QueryAnalysis:
    """Always returns a usable ``QueryAnalysis`` — see this module's
    docstring for the fallback contract."""
    deterministic = _deterministic_analysis(raw_question)

    mode = settings.query_analyzer_mode
    if (
        mode == QueryAnalyzerMode.HEURISTIC
        or not settings.query_analyzer_llm_enabled
        or llm_provider is None
    ):
        return deterministic

    try:
        llm_result = await llm_provider.generate_structured(
            system_prompt=QUERY_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=build_query_analysis_user_prompt(raw_question),
            output_schema=LLMQueryClassification,
        )
    except LLMAnalysisError as exc:
        logger.warning("LLM query analysis failed; falling back to heuristic analysis: %s", exc)
        return dataclasses.replace(deterministic, analysis_strategy="llm_fallback_heuristic")

    if mode == QueryAnalyzerMode.LLM:
        return _build_analysis(
            raw_question=deterministic.raw_question,
            normalized_question=deterministic.normalized_question,
            primary_intent=llm_result.primary_intent,
            secondary_intents=llm_result.secondary_intents,
            entities=ExtractedEntities(
                symbols=llm_result.symbols,
                file_paths=llm_result.file_paths,
                module_names=llm_result.module_names,
                class_names=llm_result.class_names,
                function_names=llm_result.function_names,
                api_routes=llm_result.api_routes,
            ),
            requested_depth=llm_result.requested_depth or deterministic.requested_depth,
            confidence=llm_result.confidence,
            analysis_strategy="llm",
        )

    return _merge_conservatively(deterministic, llm_result)

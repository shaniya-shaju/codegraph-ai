"""Deterministic abstention and confidence rules — see the answer-
generation task's "Abstention": these checks never call an LLM, run
both before generation (so we never even prompt the model when we
already know we should abstain) and after it (so a model that ignores
its own instructions still can't force an ungrounded answer through).
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.rag.enums import SymbolResolutionStatus
from app.domain.rag.models import HybridRetrievalResult, SymbolResolution
from app.rag.answer_models import AnswerConfidence, CodeCitation

_NO_EVIDENCE_MESSAGE = (
    "I could not find enough repository evidence to determine this reliably. "
    "No relevant code, symbols, or relationships were retrieved for this question."
)
_LOW_RELEVANCE_MESSAGE = (
    "I could not find enough repository evidence to determine this reliably. "
    "The evidence retrieved for this question was too weakly related to answer confidently."
)
_LLM_INSUFFICIENT_MESSAGE = (
    "I could not find enough repository evidence to determine this reliably."
)
_CITATION_FAILURE_MESSAGE = (
    "I could not verify the evidence behind this answer, so I'm withholding it rather than "
    "presenting unverified claims."
)


@dataclass(frozen=True)
class AbstentionDecision:
    should_abstain: bool
    reason: str | None = None
    message: str | None = None


def _not_found_message(resolved_symbols: list[SymbolResolution]) -> str:
    queries = ", ".join(f"`{r.query}`" for r in resolved_symbols)
    return (
        f"{_NO_EVIDENCE_MESSAGE.split('.')[0]}. "
        f"No symbol matching {queries} was found in this repository."
    )


def _ambiguous_message(ambiguous: list[SymbolResolution]) -> str:
    lines = ["I could not find enough repository evidence to determine this reliably.", ""]
    for resolution in ambiguous:
        candidate_names = [c.qualified_name or c.name for c in resolution.candidates]
        lines.append(
            f"The symbol `{resolution.query}` matches multiple functions, "
            "so the target is ambiguous:"
        )
        lines.extend(f"- {name}" for name in candidate_names)
    return "\n".join(lines)


def check_pre_generation(
    result: HybridRetrievalResult, *, settings: Settings
) -> AbstentionDecision:
    """Runs before any LLM call — see the task's abstention examples:
    "no retrieval evidence", "target symbol unresolved", "ambiguous
    symbol with no clarification-safe answer", "evidence below
    configurable relevance threshold"."""
    ambiguous = [r for r in result.resolved_symbols if r.status is SymbolResolutionStatus.AMBIGUOUS]
    any_confident = any(
        r.status in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE)
        for r in result.resolved_symbols
    )
    if ambiguous and not any_confident and result.analysis.requires_exact_symbol_search:
        return AbstentionDecision(True, "ambiguous_symbol", _ambiguous_message(ambiguous))

    if not result.evidence:
        all_not_found = bool(result.resolved_symbols) and all(
            r.status is SymbolResolutionStatus.NOT_FOUND for r in result.resolved_symbols
        )
        if all_not_found:
            return AbstentionDecision(
                True, "target_symbol_unresolved", _not_found_message(result.resolved_symbols)
            )
        return AbstentionDecision(True, "no_retrieval_evidence", _NO_EVIDENCE_MESSAGE)

    top_score = result.evidence[0].hybrid_score
    if top_score < settings.answer_min_evidence_relevance:
        return AbstentionDecision(
            True, "evidence_below_relevance_threshold", _LOW_RELEVANCE_MESSAGE
        )

    return AbstentionDecision(False)


def check_post_generation(
    *, sufficient_evidence: bool, had_citation_markers: bool, citations: list[CodeCitation]
) -> AbstentionDecision:
    """Runs after generation — catches a model that explicitly reports
    insufficient evidence, or one whose every citation attempt turned
    out invalid (see citation_validator.py)."""
    if not sufficient_evidence:
        return AbstentionDecision(
            True, "llm_reported_insufficient_evidence", _LLM_INSUFFICIENT_MESSAGE
        )
    if had_citation_markers and not citations:
        return AbstentionDecision(True, "citation_validation_failed", _CITATION_FAILURE_MESSAGE)
    return AbstentionDecision(False)


def classify_confidence(
    *,
    resolved_symbols: list[SymbolResolution],
    citations: list[CodeCitation],
    top_evidence_score: float,
    settings: Settings,
) -> tuple[AnswerConfidence, str]:
    """Deterministic, transparent confidence bucketing — never a
    statistical probability (see answer_models.py's docstring)."""
    if not citations:
        return AnswerConfidence.LOW, "The answer has little or no grounded citation support."

    any_confident_resolution = any(
        r.status in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE)
        for r in resolved_symbols
    )
    if top_evidence_score >= settings.answer_high_confidence_threshold and (
        any_confident_resolution or not resolved_symbols
    ):
        return AnswerConfidence.HIGH, "Backed by strong, directly relevant repository evidence."
    if top_evidence_score >= settings.answer_medium_confidence_threshold:
        return AnswerConfidence.MEDIUM, "Backed by moderately relevant repository evidence."
    return AnswerConfidence.LOW, "Backed only by weakly relevant repository evidence."

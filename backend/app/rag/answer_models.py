"""Typed models for grounded question answering — see the answer-
generation task's "Answer model" / "Citation model".

Confidence levels are heuristic signals about how well-grounded an answer
is, never a statistical/calibrated probability (same rule as
app.domain.rag.models's score fields — see that module's docstring).
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.rag.enums import EvidenceType, SymbolResolutionStatus


class AnswerConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class CodeCitation:
    """One validated citation — every field is copied from real retrieval
    evidence, never parsed from LLM-authored text (see "Never create a
    file path from LLM output alone")."""

    citation_id: str
    file_path: str | None
    start_line: int | None
    end_line: int | None
    symbol_id: str | None
    qualified_name: str | None
    evidence_type: EvidenceType


@dataclass(frozen=True)
class ResolvedSymbolReference:
    """A lightweight, API-facing view of one
    ``app.domain.rag.models.SymbolResolution`` — only what's useful to a
    caller of the answer, not the full candidate list."""

    query: str
    qualified_name: str | None
    symbol_id: str | None
    file_path: str | None
    start_line: int | None
    end_line: int | None
    status: SymbolResolutionStatus


@dataclass(frozen=True)
class AnswerDiagnostics:
    """Everything needed to evaluate answer quality later (Hit@K/MRR are
    retrieval-side — see app.domain.rag.models.RetrievalDiagnostics; this
    is the answer-side equivalent: latency, token counts where available,
    and exactly what was considered/rejected)."""

    retrieval_duration_ms: int
    generation_duration_ms: int
    total_duration_ms: int
    evidence_considered: int
    citations_returned: int
    invalid_citation_ids: list[str] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CodeAnswer:
    repository_id: str
    question: str

    answer: str

    citations: list[CodeCitation]

    confidence_level: AnswerConfidence
    confidence_reason: str

    retrieval_mode: str
    primary_intent: str

    resolved_symbols: list[ResolvedSymbolReference]

    limitations: list[str]

    abstained: bool

    diagnostics: AnswerDiagnostics

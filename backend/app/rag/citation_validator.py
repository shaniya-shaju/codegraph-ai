"""Citation parsing and validation — see the answer-generation task's
"Citation validation": citations are always *parsed* out of the
generated answer text (never trusted from a separately LLM-declared
list) and every cited id is checked against the real evidence pool
before it can appear as a ``CodeCitation``. An id that doesn't exist in
the pool is stripped from the visible answer, never silently kept.
"""

import re
from dataclasses import dataclass, field

from app.rag.answer_models import CodeCitation
from app.rag.citation_builder import EvidencePoolItem, evidence_pool_index

_CITATION_MARKER_RE = re.compile(r"\[E(\d+)\]")
_DEFAULT_HIGH_RELEVANCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class CitationValidationResult:
    answer_text: str
    citations: list[CodeCitation]
    invalid_ids: list[str] = field(default_factory=list)
    uncited_high_relevance_ids: list[str] = field(default_factory=list)


def validate_and_build_citations(
    raw_answer_text: str,
    pool: list[EvidencePoolItem],
    *,
    high_relevance_threshold: float = _DEFAULT_HIGH_RELEVANCE_THRESHOLD,
) -> CitationValidationResult:
    """1. Parse every ``[E<n>]`` marker out of the raw answer text.
    2. Verify each against the evidence pool.
    3. Strip markers that don't resolve to real evidence (never shown,
       never trusted) and record them as ``invalid_ids``.
    4. Renumber the surviving markers to ``[1]``, ``[2]``, ... in order
       of first appearance, and build ``CodeCitation``s whose fields are
       always copied from the real evidence pool — never from the LLM's
       own text (see "Never create a file path from LLM output alone").
    5. Best-effort flag high-relevance evidence that was retrieved but
       never cited (``uncited_high_relevance_ids``) — a heuristic signal
       for diagnostics, not a hard failure.
    """
    index = evidence_pool_index(pool)

    seen_order: list[str] = []
    invalid_ids: list[str] = []
    for match in _CITATION_MARKER_RE.finditer(raw_answer_text):
        evidence_id = f"E{match.group(1)}"
        if evidence_id in index:
            if evidence_id not in seen_order:
                seen_order.append(evidence_id)
        elif evidence_id not in invalid_ids:
            invalid_ids.append(evidence_id)

    renumbered = {evidence_id: str(i) for i, evidence_id in enumerate(seen_order, start=1)}

    def _rewrite(match: re.Match[str]) -> str:
        evidence_id = f"E{match.group(1)}"
        new_id = renumbered.get(evidence_id)
        return f"[{new_id}]" if new_id is not None else ""

    rewritten = _CITATION_MARKER_RE.sub(_rewrite, raw_answer_text)
    rewritten = re.sub(r"[ \t]{2,}", " ", rewritten)
    rewritten = re.sub(r"\s+([.,;:!?])", r"\1", rewritten)

    citations = [
        CodeCitation(
            citation_id=renumbered[evidence_id],
            file_path=index[evidence_id].evidence.file_path,
            start_line=index[evidence_id].evidence.start_line,
            end_line=index[evidence_id].evidence.end_line,
            symbol_id=index[evidence_id].evidence.symbol_id,
            qualified_name=index[evidence_id].evidence.qualified_name,
            evidence_type=index[evidence_id].evidence.evidence_type,
        )
        for evidence_id in seen_order
    ]

    uncited_high_relevance_ids = [
        item.evidence_id
        for item in pool
        if item.hybrid_score >= high_relevance_threshold and item.evidence_id not in seen_order
    ]

    return CitationValidationResult(
        answer_text=rewritten.strip(),
        citations=citations,
        invalid_ids=invalid_ids,
        uncited_high_relevance_ids=uncited_high_relevance_ids,
    )

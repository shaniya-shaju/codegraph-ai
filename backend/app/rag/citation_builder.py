"""Builds the closed, numbered "evidence pool" the LLM is allowed to cite
from, and formats it for the prompt — see the answer-generation task's
citation model: the LLM only ever sees ``E1``, ``E2``, ... ids, never the
internal ``RetrievalEvidence.id`` (a UUID-shaped/opaque string that
shouldn't leak into a user-facing citation surface).
"""

from dataclasses import dataclass

from app.domain.rag.models import RankedEvidence, RetrievalEvidence

_DEFAULT_MAX_CONTENT_CHARACTERS = 1500


@dataclass(frozen=True)
class EvidencePoolItem:
    evidence_id: str
    evidence: RetrievalEvidence
    hybrid_score: float


def build_evidence_pool(
    evidence: list[RankedEvidence], *, max_items: int
) -> list[EvidencePoolItem]:
    """Takes the already-ranked/budgeted evidence from Prompt 7's
    retrieval and exposes at most ``max_items`` of it to the LLM,
    preserving rank order (best evidence gets the lowest — and therefore
    most-likely-cited — id)."""
    return [
        EvidencePoolItem(
            evidence_id=f"E{i}", evidence=ranked.evidence, hybrid_score=ranked.hybrid_score
        )
        for i, ranked in enumerate(evidence[:max_items], start=1)
    ]


def evidence_pool_index(pool: list[EvidencePoolItem]) -> dict[str, EvidencePoolItem]:
    return {item.evidence_id: item for item in pool}


def format_evidence_block(
    pool: list[EvidencePoolItem], *, max_content_characters: int = _DEFAULT_MAX_CONTENT_CHARACTERS
) -> str:
    if not pool:
        return "(no evidence was retrieved for this question)"

    blocks = []
    for item in pool:
        ev = item.evidence
        location = (
            f"{ev.file_path}:{ev.start_line}-{ev.end_line}" if ev.file_path else "location unknown"
        )
        content = ev.content
        if len(content) > max_content_characters:
            content = content[:max_content_characters] + "\n... (truncated)"
        blocks.append(
            f"[{item.evidence_id}] type={ev.evidence_type.value} location={location} "
            f"qualified_name={ev.qualified_name or 'n/a'} source={ev.source.value}\n{content}"
        )
    return "\n\n".join(blocks)

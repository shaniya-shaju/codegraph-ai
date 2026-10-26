"""Deterministic evidence deduplication — see "Evidence deduplication".

Vector and graph retrieval frequently surface the same underlying symbol;
this merges those into one item while preserving provenance (``sources``)
and the strongest score seen from each retrieval channel, rather than
returning the same function three times.
"""

from dataclasses import dataclass, field

from app.domain.rag.enums import EvidenceSource
from app.domain.rag.models import RetrievalEvidence

# Preference order when picking which item's ``content``/citation fields
# represent a merged group — vector chunks tend to carry the fullest
# source text, symbol-resolution hits carry a confirmed exact location,
# graph-relationship hits carry the least (a one-line summary).
_SOURCE_PRIORITY = {
    EvidenceSource.VECTOR: 0,
    EvidenceSource.SYMBOL: 1,
    EvidenceSource.GRAPH: 2,
    EvidenceSource.API: 3,
}


@dataclass(frozen=True)
class DeduplicatedEvidence:
    """One post-merge evidence item, ready for context_fusion.rank_evidence."""

    evidence: RetrievalEvidence
    sources: list[EvidenceSource] = field(default_factory=list)
    vector_score: float | None = None
    graph_distance: int | None = None
    exact_match_score: float | None = None


def _merge_key(item: RetrievalEvidence) -> tuple[str, str]:
    if item.symbol_id:
        return ("symbol", f"{item.repository_id}:{item.symbol_id}")
    if item.file_path is not None:
        return (
            "location",
            f"{item.repository_id}:{item.file_path}:{item.start_line}:{item.end_line}",
        )
    return ("id", item.id)


def _pick_representative(items: list[RetrievalEvidence]) -> RetrievalEvidence:
    return min(
        items,
        key=lambda item: (_SOURCE_PRIORITY.get(item.source, 99), -len(item.content)),
    )


def deduplicate_evidence(items: list[RetrievalEvidence]) -> list[DeduplicatedEvidence]:
    groups: dict[tuple[str, str], list[RetrievalEvidence]] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        key = _merge_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged: list[DeduplicatedEvidence] = []
    for key in order:
        group = groups[key]
        representative = _pick_representative(group)

        sources: list[EvidenceSource] = []
        for item in group:
            if item.source not in sources:
                sources.append(item.source)

        vector_scores = [i.vector_score for i in group if i.vector_score is not None]
        graph_distances = [i.graph_distance for i in group if i.graph_distance is not None]
        exact_scores = [i.exact_match_score for i in group if i.exact_match_score is not None]

        merged.append(
            DeduplicatedEvidence(
                evidence=representative,
                sources=sources,
                vector_score=max(vector_scores) if vector_scores else None,
                graph_distance=min(graph_distances) if graph_distances else None,
                exact_match_score=max(exact_scores) if exact_scores else None,
            )
        )
    return merged

"""Context budgeting before (future) LLM answer generation — see "Context
budgeting". Ranked evidence is already priority-ordered; this module only
decides where to stop, never re-ranks.
"""

from app.core.config import Settings
from app.domain.rag.enums import EvidenceSource
from app.domain.rag.models import RankedEvidence


def apply_budget(
    ranked: list[RankedEvidence], *, settings: Settings
) -> tuple[list[RankedEvidence], bool]:
    """Returns ``(budgeted_evidence, truncated)``.

    - Character budget is a hard stop (``break``): once exceeded, no
      lower-ranked item is allowed to jump ahead of it just because it
      happens to be small — this preserves "preserve highest-ranked
      evidence" strictly.
    - Per-file and per-source-type caps are a ``continue`` (skip, keep
      looking): these exist for diversity ("avoid one file monopolizing
      all context"), not because the budget ran out, so a lower-ranked
      item from a different file/source is still allowed to fill the slot.
    - Citation metadata (file_path/start_line/end_line) is never
      separated from its content — evidence is only ever included or
      excluded as a whole unit.
    """
    max_items = settings.rag_max_evidence_items
    max_characters = settings.rag_max_context_characters
    max_per_file = settings.rag_max_evidence_per_file
    max_graph = settings.rag_max_graph_evidence
    max_vector = settings.rag_max_vector_evidence

    selected: list[RankedEvidence] = []
    per_file_count: dict[str, int] = {}
    graph_count = 0
    vector_count = 0
    total_characters = 0
    truncated = False

    for item in ranked:
        if len(selected) >= max_items:
            truncated = True
            break

        content_length = len(item.evidence.content)
        if total_characters + content_length > max_characters:
            truncated = True
            break

        file_key = item.evidence.file_path or "<none>"
        if per_file_count.get(file_key, 0) >= max_per_file:
            truncated = True
            continue

        is_vector = EvidenceSource.VECTOR in item.sources
        is_graph = EvidenceSource.GRAPH in item.sources or EvidenceSource.SYMBOL in item.sources
        if is_vector and vector_count >= max_vector:
            truncated = True
            continue
        if is_graph and not is_vector and graph_count >= max_graph:
            truncated = True
            continue

        selected.append(item)
        per_file_count[file_key] = per_file_count.get(file_key, 0) + 1
        total_characters += content_length
        if is_vector:
            vector_count += 1
        if is_graph and not is_vector:
            graph_count += 1

    if len(selected) < len(ranked):
        truncated = True

    return selected, truncated

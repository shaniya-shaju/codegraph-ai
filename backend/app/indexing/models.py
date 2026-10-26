"""Indexing-pipeline-internal working types.

Not part of the domain output contract (see app.domain.retrieval) — these
exist only while chunker.py is building chunks for one file. Mirrors the
pattern in app.parsing.models / app.graph's internal types.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkingLimits:
    """Resolved from Settings once per indexing run (see chunker.py)."""

    max_characters: int
    max_lines: int
    context_lines: int


@dataclass(frozen=True)
class RawFragment:
    """One piece of an oversized symbol, before it becomes a CodeChunk."""

    content: str
    start_line: int
    end_line: int

#!/usr/bin/env python3
"""Run a semantic search against an already-indexed repository and print
the ranked results.

A thin CLI over app.indexing.retrieval_service — no duplicated business
logic, no LLM call (score is a ranking signal only, see
app.indexing.retrieval_service's module docstring).

Usage:
    python scripts/inspect_vector_search.py <repository_id> "<query>" [--top-k N]
"""

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.domain.retrieval.models import VectorSearchQuery  # noqa: E402
from app.indexing.chroma_store import get_vector_store  # noqa: E402
from app.indexing.exceptions import IndexingError  # noqa: E402
from app.indexing.retrieval_service import search  # noqa: E402
from app.indexing.sentence_transformer_provider import get_embedding_provider  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_id")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    vector_query = VectorSearchQuery(
        repository_id=args.repository_id,
        query=args.query,
        top_k=args.top_k or settings.vector_default_top_k,
    )

    try:
        results = search(get_embedding_provider(), get_vector_store(), settings, vector_query)
    except IndexingError as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        return 1

    if not results:
        print("No results.")
        return 0

    for rank, result in enumerate(results, start=1):
        label = result.qualified_name or result.file_path
        print(f"{rank}. [{result.score:.3f}] {label}")
        print(f"   {result.chunk_type.value} — {result.file_path}:{result.start_line}-{result.end_line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

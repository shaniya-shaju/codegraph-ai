#!/usr/bin/env python3
"""Rebuild (or incrementally update) one repository's vector index.

Uses the same application services the API uses
(app.ingestion.analysis.analyze_and_index_repository, which delegates to
app.indexing.indexing_service) — no duplicated business logic. Re-scans
and re-parses the repository's existing on-disk workspace; never
re-uploads/re-clones and never touches the knowledge graph (use the
`POST /repositories/{id}/index` API endpoint for the same behavior over
HTTP).

Usage:
    python scripts/rebuild_vector_index.py <repository_id> [--force]
"""

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.database import get_session_factory, init_db  # noqa: E402
from app.indexing.exceptions import IndexingError  # noqa: E402
from app.ingestion.analysis import analyze_and_index_repository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_id", help="The repository_id to reindex.")
    parser.add_argument(
        "--force", action="store_true", help="Re-embed every chunk, even unchanged ones."
    )
    args = parser.parse_args()

    init_db()
    session = get_session_factory()()
    try:
        stats = analyze_and_index_repository(
            session, repository_id=args.repository_id, force_reindex=args.force
        )
    except IndexingError as exc:
        print(f"Indexing failed: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print(f"repository_id:              {stats.repository_id}")
    print(f"files parsed:               {stats.file_count}")
    print(f"symbols:                    {stats.symbol_count}")
    print(f"chunks (total):             {stats.chunk_count}")
    print(f"chunks indexed/updated:     {stats.indexed_chunk_count}")
    print(f"chunks skipped (unchanged): {stats.skipped_chunk_count}")
    print(f"stale chunks removed:       {stats.deleted_stale_chunk_count}")
    print(f"embedding model:            {stats.embedding_model}")
    print(f"embedding dimension:        {stats.embedding_dimension}")
    print(f"duration:                   {stats.duration_ms}ms")
    print(f"errors:                     {stats.error_count}")
    return 1 if stats.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

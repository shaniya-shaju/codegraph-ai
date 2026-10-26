#!/usr/bin/env python3
"""Remove every repository seeded by scripts/seed_demo_repository.py —
see the integration-reliability task's "Demo reset script".

Only ever deletes repositories whose RepositoryRecord.name matches the
fixed demo marker used by the seed script
(``codegraph-demo-python-app``) — never an arbitrary user-imported
repository, even if this script is run against a database that has other
repositories in it (see "Do not delete arbitrary user repositories.").

Calls the same app.ingestion.deletion.delete_repository_everywhere the
DELETE /repositories/{id} endpoint uses, so database records, analysis
state, conversation messages, the Chroma collection + indexing manifest,
the Neo4j repository graph, and workspace files are all cleaned up the
same way.

Usage:
    python scripts/reset_demo.py
"""

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.database import get_session_factory, init_db  # noqa: E402
from app.domain.repositories.store import list_repositories  # noqa: E402
from app.graph.neo4j_client import get_neo4j_client  # noqa: E402
from app.indexing.chroma_store import get_vector_store  # noqa: E402
from app.ingestion.deletion import delete_repository_everywhere  # noqa: E402

DEMO_REPOSITORY_NAME = "codegraph-demo-python-app"


def main() -> int:
    init_db()
    session = get_session_factory()()
    neo4j_client = get_neo4j_client()
    vector_store = get_vector_store()

    demo_repositories = [r for r in list_repositories(session) if r.name == DEMO_REPOSITORY_NAME]
    if not demo_repositories:
        print(f"No demo repository named {DEMO_REPOSITORY_NAME!r} found — nothing to reset.")
        session.close()
        return 0

    exit_code = 0
    for record in demo_repositories:
        print(f"Deleting demo repository {record.repository_id} ({DEMO_REPOSITORY_NAME})...")
        result = delete_repository_everywhere(
            session,
            repository_id=record.repository_id,
            neo4j_client=neo4j_client,
            vector_store=vector_store,
        )
        print(f"  cleaned: {result.cleaned_stores}")
        if result.errors:
            print(f"  errors:  {result.errors}")
            exit_code = 1
        else:
            print("  fully cleaned.")

    session.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Import and fully analyze the demo repository
(sample-repositories/demo-python-app) — see the integration-reliability
task's "Demo seed script".

Calls the same application services the HTTP API uses
(app.ingestion.service.import_zip_repository, which now runs the full
orchestrator pipeline — see app.ingestion.orchestrator) rather than
duplicating any analysis logic. The demo repository is zipped in-memory
from the on-disk sample-repositories/demo-python-app directory and
imported exactly like a real ZIP upload would be.

Usage:
    python scripts/seed_demo_repository.py
"""

import io
import sys
import zipfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_session_factory, init_db  # noqa: E402
from app.domain.repositories.store import list_repositories  # noqa: E402
from app.ingestion import analysis_state_service as state_service  # noqa: E402
from app.ingestion.service import import_zip_repository  # noqa: E402

DEMO_REPOSITORY_NAME = "codegraph-demo-python-app"
DEMO_REPO_DIR = Path(__file__).resolve().parents[1] / "sample-repositories" / "demo-python-app"


def _build_zip_bytes(root: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*.py")):
            archive.write(path, arcname=str(path.relative_to(root)))
        readme = root / "README.md"
        if readme.exists():
            archive.write(readme, arcname="README.md")
    return buffer.getvalue()


def main() -> int:
    if not DEMO_REPO_DIR.exists():
        print(f"Demo repository directory not found: {DEMO_REPO_DIR}", file=sys.stderr)
        return 1

    init_db()
    settings = get_settings()
    session = get_session_factory()()

    existing = [r for r in list_repositories(session) if r.name == DEMO_REPOSITORY_NAME]
    if existing:
        print(
            f"A demo repository named {DEMO_REPOSITORY_NAME!r} already exists "
            f"(repository_id={existing[0].repository_id}). Run scripts/reset_demo.py first "
            "if you want a completely fresh import."
        )

    zip_bytes = _build_zip_bytes(DEMO_REPO_DIR)
    result = import_zip_repository(
        session,
        settings,
        name=DEMO_REPOSITORY_NAME,
        filename="demo-python-app.zip",
        file_obj=io.BytesIO(zip_bytes),
    )
    record = result.record
    state = state_service.get_state(session, record.repository_id)

    print("=" * 70)
    print(
        "Demo repository ready" if record.status == "ready" else "Demo repository import finished"
    )
    print()
    print("Repository ID:")
    print(f"  {record.repository_id}")
    print()
    print(f"Files: {record.file_count}")
    if record.error_message:
        print(f"Notes: {record.error_message}")
    print()

    if state is not None:
        print("Analysis state:")
        print(
            f"  overall={state.overall_status} parser={state.parser_status} "
            f"graph={state.graph_status} vector={state.vector_status}"
        )
        print()
        print("Graph:")
        print(f"  nodes={state.graph_node_count} relationships={state.graph_relationship_count}")
        print()
        print("Vector index:")
        print(f"  chunks={state.vector_chunk_count}")
        print()

    print("Suggested demo symbols (qualified names):")
    for qn in (
        "app.services.auth_service.AuthService.login",
        "app.repositories.user_repository.UserRepository.find_by_email",
        "app.services.user_service.UserService.create_user",
        "app.api.auth.login_endpoint",
    ):
        print(f"  {qn}")
    print("=" * 70)

    session.close()
    return 0 if record.status == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())

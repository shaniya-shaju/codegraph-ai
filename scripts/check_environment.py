#!/usr/bin/env python3
"""Full environment smoke test — see Prompt 11.5 "Full environment smoke
test". Runs every infrastructure dependency CodeGraph AI needs and prints
one consolidated PASS/FAIL summary.

Reuses scripts/check_neo4j.py, scripts/check_embeddings.py, and
scripts/check_llm.py as subprocesses — each is independently runnable and
documented on its own — rather than duplicating their logic. Database,
workspace, and Chroma are checked directly here since they don't need a
dedicated script of their own.

Usage:
    python scripts/check_environment.py

Exits 0 only if every check passes.
"""

import subprocess
import sys
from pathlib import Path

_ROOT_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _ROOT_DIR / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_engine  # noqa: E402
from app.core.dependencies.models import DependencyStatus  # noqa: E402
from app.core.dependencies.status_service import check_chroma, check_database  # noqa: E402
from app.indexing.chroma_store import get_vector_store  # noqa: E402

_Result = tuple[str, bool, str | None]


def _run_script(results: list[_Result], label: str, script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(_ROOT_DIR / "scripts" / script)],
        capture_output=True,
        text=True,
        check=False,
    )
    passed = proc.returncode == 0
    reason = None
    if not passed:
        for line in (proc.stdout + proc.stderr).splitlines():
            if line.strip().startswith("Reason:"):
                reason = line.strip().removeprefix("Reason:").strip()
                break
        if reason is None:
            reason = f"see full output: python scripts/{script}"
    results.append((label, passed, reason))


def main() -> int:
    print("CodeGraph AI Environment Check")
    print()

    settings = get_settings()
    results: list[_Result] = []

    db_state = check_database(get_engine())
    results.append(("SQLite", db_state.status is DependencyStatus.READY, db_state.detail))

    workspace_ok = True
    workspace_reason = None
    for path_value, label in (
        (settings.ingestion_workspace_dir, "INGESTION_WORKSPACE_DIR"),
        (settings.ingestion_allowed_base_dir, "INGESTION_ALLOWED_BASE_DIR"),
    ):
        try:
            Path(path_value).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            workspace_ok = False
            workspace_reason = f"{label} not writable: {type(exc).__name__}"
    results.append(("Workspace", workspace_ok, workspace_reason))

    _run_script(results, "Neo4j", "check_neo4j.py")

    chroma_state = check_chroma(get_vector_store())
    results.append(("ChromaDB", chroma_state.status is DependencyStatus.READY, chroma_state.detail))

    _run_script(results, "Embeddings", "check_embeddings.py")
    _run_script(results, "LLM", "check_llm.py")

    all_passed = True
    for name, passed, reason in results:
        if passed:
            print(f"[PASS] {name}")
        else:
            all_passed = False
            print(f"[FAIL] {name}")
            if reason:
                print(f"Reason: {reason}")

    print()
    if all_passed:
        print("Environment ready.")
    else:
        print("Environment NOT fully ready — see failures above.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

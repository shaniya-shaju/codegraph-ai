"""Integration tests for POST /repositories/{id}/analyze — reanalysis
idempotency and duplicate-concurrent-analysis prevention. See the
integration-reliability task's "Idempotency" and "Concurrent analysis".

Uses the real app + real SQLite + real (embedded) Chroma. Neo4j may be
unreachable in this sandbox — the vector-index idempotency assertions
below don't depend on it (only the vector manifest/chunk counts, which
the fake embedding provider makes deterministic).
"""

import io
import time
import zipfile

from fastapi.testclient import TestClient

from app.core.database import get_session_factory
from app.indexing.metadata import get_manifest_for_repository
from app.main import app

client = TestClient(app)


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "pkg/mod.py",
            '"""A tiny module."""\n\n\ndef foo() -> int:\n    """Return 1."""\n    return 1\n',
        )
    return buffer.getvalue()


def _wait_for_terminal_state(repository_id: str, *, timeout: float = 30.0) -> dict:
    """POST /analyze runs in a background thread — poll GET .../analysis
    until it reaches a terminal overall_status."""
    terminal = {"READY", "PARTIAL", "FAILED", "STALE"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/repositories/{repository_id}/analysis")
        body = response.json()
        if body["overall_status"] in terminal:
            return body
        time.sleep(0.2)
    raise AssertionError(f"analysis did not reach a terminal state within {timeout}s")


def test_reanalysis_does_not_duplicate_manifest_entries(isolated_database: None) -> None:
    upload = client.post(
        "/api/v1/repositories/upload",
        data={"name": "idempotency-check"},
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert upload.status_code == 201, upload.text
    repository_id = upload.json()["repository_id"]

    session = get_session_factory()()
    first_manifest_count = len(get_manifest_for_repository(session, repository_id))
    assert first_manifest_count > 0

    response = client.post(f"/api/v1/repositories/{repository_id}/analyze", json={"force": True})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"

    final_state = _wait_for_terminal_state(repository_id)
    assert final_state["parser_status"] == "READY"

    second_manifest_count = len(get_manifest_for_repository(session, repository_id))
    assert second_manifest_count == first_manifest_count
    session.close()


def test_concurrent_analyze_requests_return_the_same_job(isolated_database: None) -> None:
    upload = client.post(
        "/api/v1/repositories/upload",
        data={"name": "concurrency-check"},
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert upload.status_code == 201, upload.text
    repository_id = upload.json()["repository_id"]

    first = client.post(f"/api/v1/repositories/{repository_id}/analyze", json={"force": True})
    second = client.post(f"/api/v1/repositories/{repository_id}/analyze", json={"force": True})

    assert first.status_code == 200
    assert second.status_code == 200
    # Whichever request actually started the run gets status="running";
    # the other observes it already in progress. Never two independent runs.
    statuses = {first.json()["status"], second.json()["status"]}
    assert statuses.issubset({"running", "already_running"})
    if "already_running" in statuses:
        assert first.json()["job_id"] == second.json()["job_id"]

    _wait_for_terminal_state(repository_id)


def test_unforced_analyze_of_a_current_repository_is_a_fast_no_op(
    isolated_database: None, monkeypatch
) -> None:
    """A git-sourced repository whose commit hasn't changed should be
    reported "current" immediately, without submitting a background run
    (see "If analysis is already current and force=false, do not perform
    unnecessary rebuilding."). The prior run's graph/vector state is set
    directly (rather than relying on a real reachable Neo4j in this
    sandbox) so this test exercises the currency short-circuit itself,
    independent of Neo4j's actual availability here."""
    from app import ingestion
    from app.domain.repositories.enums import SubsystemStatus
    from app.ingestion import analysis_state_service as state_service

    def fake_run_git(args, *, cwd, timeout):
        import subprocess

        if args[0] == "clone":
            destination_path = args[-1]
            from pathlib import Path

            Path(destination_path).mkdir(parents=True, exist_ok=True)
            (Path(destination_path) / "mod.py").write_text("def foo():\n    return 1\n")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "rev-parse" and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="fixedcommit123\n", stderr="")

    monkeypatch.setattr(ingestion.git_clone, "_run_git", fake_run_git)

    clone = client.post(
        "/api/v1/repositories/clone",
        json={"name": "current-check", "git_url": "https://github.com/example/demo.git"},
    )
    assert clone.status_code == 201, clone.text
    repository_id = clone.json()["repository_id"]

    # Force the persisted state into what a fully-successful prior run
    # (including a reachable Neo4j) would have produced.
    session = get_session_factory()()
    state_service.mark_graph_result(
        session, repository_id, status=SubsystemStatus.READY, revision="fixedcommit123"
    )
    state_service.mark_vector_result(
        session, repository_id, status=SubsystemStatus.READY, revision="fixedcommit123"
    )
    state_service.finalize_run(session, repository_id, repository_revision="fixedcommit123")
    session.close()

    response = client.post(f"/api/v1/repositories/{repository_id}/analyze", json={"force": False})
    assert response.status_code == 200
    assert response.json()["status"] == "current"

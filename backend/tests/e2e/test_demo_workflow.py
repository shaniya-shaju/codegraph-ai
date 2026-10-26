"""End-to-end backend workflow test — see the integration-reliability
task's "End-to-end test": import -> analyze -> confirm subsystem
readiness -> semantic/graph/hybrid retrieval -> grounded Q&A with
citations -> impact analysis -> reanalysis idempotency -> deletion +
cleanup verification.

Uses: real SQLite (via ``isolated_database``), real embedded Chroma, real
Neo4j (skips visibly via tests/e2e/conftest.py if unreachable — never
faked), and a fake LLM provider (no paid API credentials required — see
"Do not require paid API credentials.").
"""

import io
import re
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import query as query_routes
from app.core.database import get_session_factory
from app.indexing.metadata import get_manifest_for_repository
from app.ingestion.analysis import repository_workspace
from app.main import app

_DEMO_REPO_DIR = Path(__file__).resolve().parents[3] / "sample-repositories" / "demo-python-app"


class _SmartFakeLLMProvider:
    """No paid LLM credentials are used for this test — inspects the
    real evidence pool it's given and cites whatever is actually there,
    exercising the real citation-building/validation pipeline end-to-end
    (same disclosed technique as this project's other manual/e2e
    verification scripts)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate_structured(self, *, system_prompt, user_prompt, output_schema):
        self.calls.append(user_prompt)
        ids = re.findall(r"\[(E\d+)\]", user_prompt)
        unique_ids = list(dict.fromkeys(ids))[:2]
        if not unique_ids:
            return output_schema(answer="Not enough evidence.", sufficient_evidence=False)
        cites = " ".join(f"[{eid}]" for eid in unique_ids)
        return output_schema(
            answer=f"Based on the repository evidence, {cites}.", sufficient_evidence=True
        )

    async def generate_text_stream(self, *, system_prompt, user_prompt):  # pragma: no cover
        yield "unused"


def _zip_demo_repo() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(_DEMO_REPO_DIR.rglob("*.py")):
            archive.write(path, arcname=str(path.relative_to(_DEMO_REPO_DIR)))
    return buffer.getvalue()


def test_full_demo_workflow(isolated_database: None, neo4j_ready: None) -> None:
    fake_llm = _SmartFakeLLMProvider()
    app.dependency_overrides[query_routes._llm_provider] = lambda: fake_llm
    client = TestClient(app)

    try:
        # 1. Register/import the demo repository.
        upload = client.post(
            "/api/v1/repositories/upload",
            data={"name": "e2e-demo-python-app"},
            files={"file": ("demo.zip", _zip_demo_repo(), "application/zip")},
        )
        assert upload.status_code == 201, upload.text
        repository_id = upload.json()["repository_id"]

        # 2. Analysis already ran synchronously as part of import — confirm
        # its persisted state.
        state = client.get(f"/api/v1/repositories/{repository_id}/analysis").json()

        # 3-5. Confirm parser/graph/vector READY.
        assert state["parser_status"] == "READY", state
        assert state["graph_status"] == "READY", state
        assert state["vector_status"] == "READY", state

        # 6. Confirm repository overall READY.
        assert state["overall_status"] == "READY", state

        # 7. Semantic search (vector-only retrieval).
        retrieve_vector = client.post(
            f"/api/v1/repositories/{repository_id}/retrieve",
            json={"question": "Where is authentication implemented?", "mode": "vector"},
        )
        assert retrieve_vector.status_code == 200, retrieve_vector.text
        assert len(retrieve_vector.json()["evidence"]) > 0

        # 8. Graph search (graph-only retrieval).
        retrieve_graph = client.post(
            f"/api/v1/repositories/{repository_id}/retrieve",
            json={"question": "Which functions call AuthService.login?", "mode": "graph"},
        )
        assert retrieve_graph.status_code == 200, retrieve_graph.text
        assert len(retrieve_graph.json()["evidence"]) > 0

        # 9. Hybrid retrieval.
        retrieve_hybrid = client.post(
            f"/api/v1/repositories/{repository_id}/retrieve",
            json={"question": "Explain AuthService.login in simple terms.", "mode": "hybrid"},
        )
        assert retrieve_hybrid.status_code == 200, retrieve_hybrid.text
        assert len(retrieve_hybrid.json()["evidence"]) > 0

        # 10. Grounded question with citations (fake LLM).
        answer_response = client.post(
            f"/api/v1/repositories/{repository_id}/query",
            json={"question": "Explain AuthService.login in simple terms."},
        )
        assert answer_response.status_code == 200, answer_response.text
        answer = answer_response.json()
        assert answer["abstained"] is False
        assert answer["citations"], answer

        # 11. Validate citation file and lines.
        for citation in answer["citations"]:
            assert citation["file_path"].endswith(".py")
            assert citation["start_line"] >= 1
            assert citation["end_line"] >= citation["start_line"]

        # 12. Impact analysis on AuthService.login.
        impact_response = client.get(
            f"/api/v1/repositories/{repository_id}/impact/placeholder",
            params={"qualified_name": "app.services.auth_service.AuthService.login"},
        )
        assert impact_response.status_code == 200, impact_response.text
        impact = impact_response.json()
        assert impact["target"]["qualified_name"] == "app.services.auth_service.AuthService.login"

        # 13. Validate affected endpoint (POST /login reaches AuthService.login).
        assert any(e["route_path"] == "/login" for e in impact["affected_endpoints"]), impact[
            "affected_endpoints"
        ]

        session = get_session_factory()()
        manifest_before = len(get_manifest_for_repository(session, repository_id))
        node_count_before = state["graph_node_count"]

        # 14. Re-run analysis.
        analyze_response = client.post(
            f"/api/v1/repositories/{repository_id}/analyze", json={"force": True}
        )
        assert analyze_response.status_code == 200, analyze_response.text

        import time

        deadline = time.monotonic() + 30
        rerun_state = None
        while time.monotonic() < deadline:
            rerun_state = client.get(f"/api/v1/repositories/{repository_id}/analysis").json()
            if rerun_state["overall_status"] in ("READY", "PARTIAL", "FAILED", "STALE"):
                break
            time.sleep(0.2)
        assert rerun_state is not None and rerun_state["overall_status"] == "READY", rerun_state

        # 15. Confirm idempotency — no duplicate manifest rows or graph nodes.
        manifest_after = len(get_manifest_for_repository(session, repository_id))
        assert manifest_after == manifest_before
        assert rerun_state["graph_node_count"] == node_count_before
        session.close()

        # 16. Delete the repository.
        delete_response = client.delete(f"/api/v1/repositories/{repository_id}")
        assert delete_response.status_code == 200, delete_response.text

        # 17. Confirm external stores cleaned up.
        assert client.get(f"/api/v1/repositories/{repository_id}/analysis").status_code == 404
        session = get_session_factory()()
        assert get_manifest_for_repository(session, repository_id) == []
        assert not repository_workspace(repository_id).exists()
        session.close()

        symbol_lookup = client.get(f"/api/v1/repositories/{repository_id}/impact/anything")
        assert symbol_lookup.status_code == 404
    finally:
        app.dependency_overrides.pop(query_routes._llm_provider, None)

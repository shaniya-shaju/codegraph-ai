"""Integration test for repository deletion cleanup — see the
integration-reliability task's "Repository deletion": ordered cleanup
across the application database, analysis state, conversation messages,
Chroma + indexing manifest, the Neo4j graph, and workspace files.

Uses the real app + a real (embedded) Chroma + real SQLite. Neo4j may or
may not be reachable in this environment; the graph-cleanup step is
allowed to report an error in ``result.errors`` when it is unreachable
(the assertion below accounts for both cases) — this test's purpose is to
verify the *ordering/collection* contract (see
app.ingestion.deletion.delete_repository_everywhere), not to require a
live Neo4j.
"""

import io
import zipfile

from fastapi.testclient import TestClient

from app.core.database import get_session_factory
from app.domain.repositories.store import get_repository
from app.indexing.metadata import get_manifest_for_repository
from app.ingestion import analysis_state_service as state_service
from app.ingestion.analysis import repository_workspace
from app.main import app
from app.rag.conversation_context import (
    ConversationRole,
    append_turn,
    get_conversation_repository_id,
)

client = TestClient(app)


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pkg/mod.py", "def foo():\n    return 1\n")
    return buffer.getvalue()


def test_deleting_a_repository_cleans_up_every_store(isolated_database: None) -> None:
    upload = client.post(
        "/api/v1/repositories/upload",
        data={"name": "delete-me"},
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert upload.status_code == 201, upload.text
    repository_id = upload.json()["repository_id"]

    session = get_session_factory()()
    # Record a conversation turn too, so its cleanup is also verified.
    append_turn(
        session,
        conversation_id="conv-1",
        repository_id=repository_id,
        role=ConversationRole.USER,
        message="hello",
    )
    workspace = repository_workspace(repository_id)
    assert workspace.exists()

    response = client.delete(f"/api/v1/repositories/{repository_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "neo4j_graph" in body["cleaned"] or "neo4j_graph" in [
        e.split(":")[0] for e in body["errors"]
    ]

    # Application database record gone.
    assert get_repository(session, repository_id) is None
    # Analysis state gone.
    assert state_service.get_state(session, repository_id) is None
    # Conversation messages gone.
    assert get_conversation_repository_id(session, "conv-1") is None
    # Indexing manifest gone.
    assert get_manifest_for_repository(session, repository_id) == []
    # Workspace files gone.
    assert not workspace.exists()

    session.close()


def test_deleting_an_unknown_repository_returns_404(isolated_database: None) -> None:
    response = client.delete("/api/v1/repositories/does-not-exist")
    assert response.status_code == 404

"""Contract test for GET /api/v1/health — see API_SPEC.md "Health" and
app.api.routes.health's docstring on the degraded-vs-failed choice.

All three dependencies (Neo4j, ChromaDB, the embedding provider) are
mocked so this stays fast, deterministic, and offline — it must never
trigger a real embedding-model load (see the indexing task: "Avoid
forcing expensive model loading on every lightweight liveness request")."""

from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app

client = TestClient(app)


class _FakeNeo4jClient:
    def __init__(self, status: str) -> None:
        self._status = status

    def health_status(self) -> str:
        return self._status


class _FakeVectorStore:
    def __init__(self, status: str) -> None:
        self._status = status

    def health_check(self) -> str:
        return self._status


class _FakeEmbeddingProvider:
    def __init__(self, *, loaded: bool) -> None:
        self._loaded = loaded
        self.model_name = "fake-model"

    def is_loaded(self) -> bool:
        return self._loaded


def _patch_dependencies(
    monkeypatch, *, neo4j_status: str, chroma_status: str, embedding_loaded: bool
) -> None:
    monkeypatch.setattr(health, "get_neo4j_client", lambda: _FakeNeo4jClient(neo4j_status))
    monkeypatch.setattr(health, "get_vector_store", lambda: _FakeVectorStore(chroma_status))
    monkeypatch.setattr(
        health, "get_embedding_provider", lambda: _FakeEmbeddingProvider(loaded=embedding_loaded)
    )


def test_health_reports_ok_when_all_dependencies_are_reachable(monkeypatch) -> None:
    _patch_dependencies(monkeypatch, neo4j_status="ok", chroma_status="ok", embedding_loaded=False)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "codegraph-api"
    assert body["dependencies"] == {"neo4j": "ok", "chromadb": "ok"}


def test_health_reports_degraded_but_still_200_when_neo4j_is_unavailable(monkeypatch) -> None:
    _patch_dependencies(
        monkeypatch, neo4j_status="unavailable", chroma_status="ok", embedding_loaded=False
    )

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["neo4j"] == "unavailable"


def test_health_reports_degraded_when_chromadb_is_unavailable(monkeypatch) -> None:
    _patch_dependencies(
        monkeypatch, neo4j_status="ok", chroma_status="unavailable", embedding_loaded=False
    )

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["chromadb"] == "unavailable"


def test_health_reports_embedding_provider_load_state_without_loading_it(monkeypatch) -> None:
    _patch_dependencies(monkeypatch, neo4j_status="ok", chroma_status="ok", embedding_loaded=False)

    response = client.get("/api/v1/health")

    body = response.json()
    assert body["embedding_provider"] == {"model_name": "fake-model", "status": "not_loaded"}


def test_health_reports_loaded_when_embedding_provider_already_loaded(monkeypatch) -> None:
    _patch_dependencies(monkeypatch, neo4j_status="ok", chroma_status="ok", embedding_loaded=True)

    response = client.get("/api/v1/health")

    body = response.json()
    assert body["embedding_provider"]["status"] == "loaded"

"""HTTP-level integration tests for liveness/readiness, request
correlation, and the standardized error contract — see the integration-
reliability task's "Integration tests" list (items 1-3, 10). Uses the
real app; Neo4j may or may not be reachable in this environment — these
assertions hold either way (readiness degrades gracefully rather than
requiring a specific dependency state)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestLiveness:
    def test_live_is_always_instant_and_ok(self) -> None:
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "codegraph-api"

    def test_live_never_returns_dependency_details(self) -> None:
        response = client.get("/api/v1/health/live")
        assert "dependencies" not in response.json()


class TestReadiness:
    def test_ready_reports_every_known_dependency(self) -> None:
        response = client.get("/api/v1/health/ready")
        assert response.status_code in (200, 503)
        body = response.json()
        assert set(body["dependencies"].keys()) == {
            "database",
            "neo4j",
            "chroma",
            "embedding_provider",
            "llm",
        }

    def test_ready_never_leaks_credentials_or_paths(self) -> None:
        response = client.get("/api/v1/health/ready")
        raw = response.text.lower()
        assert "changeme" not in raw
        assert "bolt://" not in raw
        assert "sqlite:///" not in raw

    def test_database_dependency_is_ready(self) -> None:
        # The application database itself is always reachable in these
        # tests (SQLite file/engine created by init_db()).
        response = client.get("/api/v1/health/ready")
        assert response.json()["dependencies"]["database"]["status"] == "READY"


class TestRequestCorrelation:
    def test_response_always_has_a_request_id_header(self) -> None:
        response = client.get("/api/v1/health/live")
        assert response.headers.get("x-request-id")

    def test_a_safe_incoming_request_id_is_echoed_back(self) -> None:
        response = client.get(
            "/api/v1/health/live", headers={"X-Request-ID": "caller-supplied-id-123"}
        )
        assert response.headers["x-request-id"] == "caller-supplied-id-123"

    def test_an_unsafe_incoming_request_id_is_replaced(self) -> None:
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": "not safe! <script>"})
        assert response.headers["x-request-id"] != "not safe! <script>"

    def test_different_requests_get_different_ids_by_default(self) -> None:
        first = client.get("/api/v1/health/live").headers["x-request-id"]
        second = client.get("/api/v1/health/live").headers["x-request-id"]
        assert first != second


class TestErrorContract:
    def test_missing_repository_returns_standard_error_shape(self, isolated_database: None) -> None:
        response = client.get("/api/v1/repositories/does-not-exist/analysis")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert "retryable" in body["error"]
        assert "details" in body["error"]
        assert "request_id" in body
        assert response.headers["x-request-id"] == body["request_id"]

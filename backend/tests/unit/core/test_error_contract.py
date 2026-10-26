"""Unit tests for the standardized error-response contract — see
app.core.exceptions: {"error": {"code","message","retryable","details"}}
plus a top-level "request_id"."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AnalysisAlreadyRunningError,
    ConflictError,
    GraphUnavailableError,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)
from app.core.request_context import request_id_middleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_id_middleware)
    register_exception_handlers(app)

    @app.get("/not-found")
    def _not_found() -> None:
        raise NotFoundError("missing")

    @app.get("/validation")
    def _validation() -> None:
        raise ValidationError("bad request", details={"field": "name"})

    @app.get("/conflict")
    def _conflict() -> None:
        raise ConflictError("already exists")

    @app.get("/graph-unavailable")
    def _graph_unavailable() -> None:
        raise GraphUnavailableError("graph is down")

    @app.get("/already-running")
    def _already_running() -> None:
        raise AnalysisAlreadyRunningError("running", details={"job_id": "abc"})

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("unexpected internal failure detail")

    return app


client = TestClient(_make_app())
# Unexpected (non-AppError) exceptions must produce a clean 500 response,
# not propagate through TestClient — matches real ASGI-server behavior.
client_no_raise = TestClient(_make_app(), raise_server_exceptions=False)


class TestKnownErrors:
    def test_not_found_shape(self) -> None:
        response = client.get("/not-found")
        assert response.status_code == 404
        body = response.json()["error"]
        assert body["code"] == "NOT_FOUND"
        assert body["retryable"] is False
        assert body["details"] == {}
        assert "request_id" in response.json()

    def test_validation_error_shape_and_details(self) -> None:
        response = client.get("/validation")
        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "VALIDATION_ERROR"
        assert body["details"] == {"field": "name"}

    def test_conflict_shape(self) -> None:
        response = client.get("/conflict")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_graph_unavailable_is_retryable(self) -> None:
        response = client.get("/graph-unavailable")
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "GRAPH_UNAVAILABLE"
        assert body["retryable"] is True

    def test_analysis_already_running_is_409_and_retryable(self) -> None:
        response = client.get("/already-running")
        assert response.status_code == 409
        body = response.json()["error"]
        assert body["code"] == "ANALYSIS_ALREADY_RUNNING"
        assert body["retryable"] is True
        assert body["details"] == {"job_id": "abc"}


class TestUnexpectedError:
    def test_never_leaks_the_raw_exception_message(self) -> None:
        response = client_no_raise.get("/boom")
        assert response.status_code == 500
        body = response.json()["error"]
        assert body["code"] == "INTERNAL_ERROR"
        assert "unexpected internal failure detail" not in body["message"]

    def test_has_a_request_id(self) -> None:
        response = client_no_raise.get("/boom")
        assert "request_id" in response.json()


class TestRequestIdPresence:
    def test_error_response_includes_the_same_id_as_the_header(self) -> None:
        response = client.get("/not-found")
        assert response.json()["request_id"] == response.headers["x-request-id"]

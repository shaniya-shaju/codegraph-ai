"""Application exception types and their FastAPI error-response mapping.

Implements the standardized error contract (see the integration-
reliability task's "Error contract"):

    {
      "error": {
        "code": "...",
        "message": "...",
        "retryable": false,
        "details": {}
      }
    }

``retryable`` is a hint for callers (e.g. the future frontend): true means
"the same request may succeed if retried later" (a dependency outage), false
means "retrying without changing the request won't help" (a validation
error, a missing resource). ``details`` is a small, always-safe structured
payload — never a stack trace, credential, connection string, or local
filesystem path (see SECURITY.md and this module's own rule below).
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that map to a known HTTP status and error code."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    """A requested resource (e.g. a repository_id) does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ValidationError(AppError):
    """The request was well-formed JSON but failed a domain rule."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"


class ConflictError(AppError):
    """The request conflicts with the resource's current state."""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class UnsupportedMediaTypeError(AppError):
    """The uploaded content is not a supported/valid archive type."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "UNSUPPORTED_MEDIA_TYPE"


class PayloadTooLargeError(AppError):
    """The upload, or its extracted/cloned content, exceeds a configured size limit."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "PAYLOAD_TOO_LARGE"


class UnsafeArchiveError(AppError):
    """The archive contains a path-traversal, absolute-path, or symlink entry."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "UNSAFE_ARCHIVE"


class InvalidGitUrlError(AppError):
    """The provided git URL is not an allowed public HTTPS reference."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_GIT_URL"


class GitCloneError(AppError):
    """Cloning the repository failed (timeout, size limit, or a git failure)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "GIT_CLONE_FAILED"


class GitHostNotAllowedError(AppError):
    """The git URL's host is not on the configured allow-list
    (REPO_CLONE_ALLOWED_HOSTS) — distinct from InvalidGitUrlError (a
    structurally unsafe URL) so the frontend can show a more specific
    message. See SECURITY.md "Repository acquisition safety"."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "GIT_HOST_NOT_ALLOWED"


class GitCloningDisabledError(AppError):
    """REPO_URL_CLONE_ENABLED is false — URL-based repository import is
    turned off on this server. Local-path and ZIP-upload ingestion are
    unaffected."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "GIT_CLONING_DISABLED"


class GraphUnavailableError(AppError):
    """Neo4j is required for this request but is not reachable.

    See SECURITY.md / ARCHITECTURE.md: the graph is the structural source
    of truth, so a query that needs it fails clearly rather than degrading
    silently (this is distinct from GET /health/ready, which reports
    Neo4j status without failing the whole readiness check — see
    api/routes/health.py). Retryable: the same request will likely
    succeed once Neo4j (or the circuit breaker's cooldown) recovers.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "GRAPH_UNAVAILABLE"
    retryable = True


class VectorIndexUnavailableError(AppError):
    """ChromaDB is required for this request but is not reachable/usable."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "VECTOR_INDEX_UNAVAILABLE"
    retryable = True


class EmbeddingProviderUnavailableError(AppError):
    """The embedding model failed to load or failed while embedding a request."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "EMBEDDING_PROVIDER_UNAVAILABLE"
    retryable = True


class InvalidTraversalParameterError(AppError):
    """A depth/limit/relationship-type parameter is missing, out of the
    configured bounds, or not on the relationship-type allow-list."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_TRAVERSAL_PARAMETER"


class SymbolNotFoundApiError(AppError):
    """No symbol matched the given symbol_id/qualified_name."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "SYMBOL_NOT_FOUND"


class AmbiguousSymbolApiError(AppError):
    """A qualified_name matched more than one equally-ranked candidate —
    see the candidate list in ``details``."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "AMBIGUOUS_SYMBOL"


class AnalysisAlreadyRunningError(AppError):
    """A second analysis was requested for a repository that already has
    one in progress. Retryable in the sense that polling/retrying later
    (once the existing run finishes) is the correct caller behavior."""

    status_code = status.HTTP_409_CONFLICT
    code = "ANALYSIS_ALREADY_RUNNING"
    retryable = True


class AnalysisFailedError(AppError):
    """A repository's analysis (parse/graph/vector) failed terminally."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "ANALYSIS_FAILED"


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    from app.core.request_context import get_request_id

    request_id = get_request_id()
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        }
    }
    if request_id is not None:
        body["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire AppError (and a catch-all fallback) into the FastAPI app."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            exc.status_code, exc.code, exc.message, retryable=exc.retryable, details=exc.details
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Full exception (with traceback) goes to the server-side log only
        # — never to the client (see "Do not leak stack traces.").
        logger.exception(
            "Unhandled exception while processing %s %s",
            request.method,
            request.url.path,
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
        )

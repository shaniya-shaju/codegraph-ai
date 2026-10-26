"""Request-correlation-id plumbing — see the integration-reliability
task's "Request correlation": every API request gets an id, returned in
``X-Request-ID`` and available to structured log records via
``RequestIdLogFilter`` (see app.core.logging) and to error responses (see
app.core.exceptions) without threading it through every function call.

A ``contextvars.ContextVar`` (not a global variable) is used so this is
safe under FastAPI's concurrent request handling — each request gets its
own isolated value, including across ``await`` points.
"""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.requests import Request
from starlette.responses import Response

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_access_logger = logging.getLogger("app.access")

# A conservative allow-list for a caller-supplied X-Request-ID — never
# reflect an unbounded/malformed header value back verbatim into logs or
# responses (see SECURITY.md "sanitize errors").
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def new_request_id() -> str:
    return str(uuid.uuid4())


def sanitize_incoming_request_id(value: str | None) -> str | None:
    """A caller-supplied correlation id is only reused if it looks safe;
    otherwise a fresh one is generated — never trust an arbitrary
    incoming header value verbatim."""
    if value and _SAFE_REQUEST_ID_RE.match(value):
        return value
    return None


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def get_request_id() -> str | None:
    return _request_id_var.get()


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Generate (or accept a safe incoming) correlation id for every
    request, expose it to error responses/log records for the duration of
    the request, echo it back as ``X-Request-ID``, and emit one compact
    access-log line per request (method, path, status, duration_ms,
    request_id) — see "Structured logging": "Useful operations include...".

    Never logs the request body/query string (could contain repository
    source excerpts via search/query endpoints) — see "Do not log complete
    repository code." / "Do not log full prompts at INFO level.".
    """
    incoming = sanitize_incoming_request_id(request.headers.get("x-request-id"))
    request_id = incoming or new_request_id()
    set_request_id(request_id)

    started = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - started) * 1000)

    response.headers["X-Request-ID"] = request_id
    _access_logger.info(
        "%s %s -> %d",
        request.method,
        request.url.path,
        response.status_code,
        extra={
            "request_id": request_id,
            "operation": "http_request",
            "duration_ms": duration_ms,
            "status": response.status_code,
        },
    )
    return response


class RequestIdLogFilter(logging.Filter):
    """Stamps the current request's correlation id onto every log record
    emitted while handling that request — see app.core.logging, which
    installs this filter on the root handler so *any* ``logger.info(...)``
    call anywhere in the codebase picks it up automatically, with no
    per-call-site change needed."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        return True

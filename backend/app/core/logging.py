"""Logging configuration.

Deliberately plain stdlib logging for the MVP — see AGENTS.md rule 9
(avoid unnecessary abstractions). Reach for structured logging only when a
concrete requirement (log aggregation, tracing) demands it.

Every log line carries a consistent ``request_id`` field (via
``RequestIdLogFilter`` — "-" outside any request, e.g. at startup or in a
background analysis thread) so log lines from one API call can be
correlated even across modules — see the integration-reliability task's
"Structured logging" / "Request correlation". Callers that want the
richer fields (``operation``, ``duration_ms``, ``repository_id``,
``job_id``, ``status``) pass them via ``logger.info(msg, extra={...})``;
nothing here forces every call site to supply them.
"""

import logging
import sys

from app.core.config import Settings
from app.core.request_context import RequestIdLogFilter

_LOG_FORMAT = "%(asctime)s %(levelname)s [request_id=%(request_id)s] %(name)s: %(message)s"


def configure_logging(settings: Settings) -> None:
    """Configure the root logger once, at application startup."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(RequestIdLogFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

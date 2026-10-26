"""Typed dependency-readiness models — see the integration-reliability
task's "Liveness and readiness": "Allowed dependency states should be
explicit."
"""

from dataclasses import dataclass, field
from enum import StrEnum


class DependencyStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_LOADED = "NOT_LOADED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DependencyState:
    name: str
    status: DependencyStatus
    # Short, safe, human-readable context only — never a credential,
    # connection string, or local filesystem path (see "Do not expose:
    # passwords / connection strings containing credentials / local
    # filesystem paths / API keys.").
    detail: str | None = None
    # Non-secret configuration identifiers, populated only for
    # dependencies where naming the configured model/provider is useful
    # diagnostic information (currently "llm" and "embedding_provider") —
    # see Prompt 11.5 "Setup wizard / diagnostic endpoint". Never a
    # credential, URL, or path.
    model: str | None = None
    provider: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    status: str  # "ready" | "degraded" | "unavailable"
    dependencies: dict[str, DependencyState] = field(default_factory=dict)

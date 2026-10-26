"""Centralized dependency-status checks — the single place `/health/ready`
(and anything else that needs it) asks "is X currently usable?" instead of
each endpoint performing its own health logic (see this package's
``__init__`` docstring).

Every check here is cheap and bounded: the Neo4j check never blocks for
longer than its circuit breaker/operation-timeout already bound (see
app.graph.neo4j_client), the database check is a trivial ``SELECT 1``, the
Chroma check reuses its own already-fast ``health_check()``, and the
embedding-provider check never triggers a model load (see "Lazy embedding
model behavior": "`/health/live` must never trigger model loading.").
"""

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.core.dependencies.circuit_breaker import CircuitState
from app.core.dependencies.models import DependencyState, DependencyStatus, ReadinessReport
from app.graph.neo4j_client import Neo4jClient
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.vector_store import VectorStore
from app.rag.llm_provider import normalize_llm_provider


def check_database(engine: Engine) -> DependencyState:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return DependencyState("database", DependencyStatus.READY)
    except Exception as exc:  # noqa: BLE001 - any DB failure means UNAVAILABLE
        return DependencyState("database", DependencyStatus.UNAVAILABLE, detail=type(exc).__name__)


def check_neo4j(client: Neo4jClient) -> DependencyState:
    if client.circuit_state is CircuitState.OPEN:
        return DependencyState(
            "neo4j", DependencyStatus.UNAVAILABLE, detail="circuit_open_recent_failures"
        )
    if client.verify_connectivity():
        return DependencyState("neo4j", DependencyStatus.READY)
    return DependencyState("neo4j", DependencyStatus.UNAVAILABLE)


def check_chroma(vector_store: VectorStore) -> DependencyState:
    try:
        status = vector_store.health_check()
    except Exception as exc:  # noqa: BLE001
        return DependencyState("chroma", DependencyStatus.UNAVAILABLE, detail=type(exc).__name__)
    return DependencyState(
        "chroma",
        DependencyStatus.READY if status == "ok" else DependencyStatus.UNAVAILABLE,
    )


def check_embedding_provider(provider: EmbeddingProvider) -> DependencyState:
    """Never triggers a model load — only reports whether an earlier
    request already loaded it (see "embedding_provider = NOT_LOADED if no
    request has yet required it.")."""
    try:
        loaded = provider.is_loaded()
        model_name = provider.model_name
    except Exception as exc:  # noqa: BLE001
        return DependencyState(
            "embedding_provider", DependencyStatus.UNAVAILABLE, detail=type(exc).__name__
        )
    return DependencyState(
        "embedding_provider",
        DependencyStatus.READY if loaded else DependencyStatus.NOT_LOADED,
        model=model_name,
    )


def check_llm(settings: Settings) -> DependencyState:
    """Reports the configured LLM's status without ever generating real
    text (see Prompt 11.5 "LLM connectivity check"). Distinguishes three
    situations, encoded as (status, detail) rather than new
    DependencyStatus members — reusing the existing enum per this
    prompt's own "reuse over duplicate" guidance — see each branch below:

    - "not configured": required settings are missing/placeholder values
      (``DependencyStatus.NOT_LOADED``, ``detail="not_configured"``).
    - "unavailable": configured but unreachable, or (for an
      OpenAI-compatible server that lists its models) the configured
      model isn't currently being served (``DependencyStatus.UNAVAILABLE``).
    - "ready": configured and, where cheaply verifiable, reachable
      (``DependencyStatus.READY``).

    A cloud provider (e.g. "anthropic") never makes a live network call
    here — unlike LM Studio, an API request costs real money, and
    readiness is polled repeatedly (see DependencyBanner on the
    frontend), so this only checks that credentials/model look present.
    """
    provider = normalize_llm_provider(settings.llm_provider)

    if provider != "openai_compatible":
        if not settings.llm_model or not settings.llm_api_key or settings.llm_api_key == "changeme":
            return DependencyState(
                "llm",
                DependencyStatus.NOT_LOADED,
                detail="not_configured",
                provider=provider,
                model=settings.llm_model or None,
            )
        return DependencyState(
            "llm",
            DependencyStatus.READY,
            detail="not_verified_live",
            provider=provider,
            model=settings.llm_model,
        )

    if not settings.llm_base_url or not settings.llm_model:
        return DependencyState(
            "llm",
            DependencyStatus.NOT_LOADED,
            detail="not_configured",
            provider=provider,
            model=settings.llm_model or None,
        )

    base_url = settings.llm_base_url.rstrip("/")
    headers = (
        {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    )
    try:
        response = httpx.get(
            f"{base_url}/models",
            headers=headers,
            timeout=settings.llm_health_check_timeout_seconds,
        )
        response.raise_for_status()
        served_model_ids = {
            item.get("id")
            for item in response.json().get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
    except Exception as exc:  # noqa: BLE001 - any connectivity failure means UNAVAILABLE
        return DependencyState(
            "llm",
            DependencyStatus.UNAVAILABLE,
            detail=type(exc).__name__,
            provider=provider,
            model=settings.llm_model,
        )

    if served_model_ids and settings.llm_model not in served_model_ids:
        return DependencyState(
            "llm",
            DependencyStatus.UNAVAILABLE,
            detail="configured_model_not_served",
            provider=provider,
            model=settings.llm_model,
        )
    return DependencyState(
        "llm", DependencyStatus.READY, provider=provider, model=settings.llm_model
    )


# Dependencies whose unavailability makes the whole backend UNAVAILABLE
# (nothing works without the application database).
_CRITICAL_FOR_READY = frozenset({"database"})


def get_readiness_report(
    *,
    engine: Engine,
    neo4j_client: Neo4jClient,
    vector_store: VectorStore,
    embedding_provider: EmbeddingProvider,
    settings: Settings,
) -> ReadinessReport:
    dependencies = {
        "database": check_database(engine),
        "neo4j": check_neo4j(neo4j_client),
        "chroma": check_chroma(vector_store),
        "embedding_provider": check_embedding_provider(embedding_provider),
        "llm": check_llm(settings),
    }

    if any(
        dependencies[name].status is DependencyStatus.UNAVAILABLE for name in _CRITICAL_FOR_READY
    ):
        overall = "unavailable"
    elif any(
        state.status is DependencyStatus.UNAVAILABLE
        for name, state in dependencies.items()
        if name not in _CRITICAL_FOR_READY
    ):
        # Neo4j or Chroma down: some operations degrade (see "Graceful
        # degradation") but the backend as a whole is still usable.
        overall = "degraded"
    else:
        overall = "ready"

    return ReadinessReport(status=overall, dependencies=dependencies)

"""Liveness and readiness checks — see the integration-reliability task's
"Liveness and readiness": these answer two different questions and must
behave very differently.

``GET /health/live`` — "Is the FastAPI process running?" Always instant:
no Neo4j query, no Chroma call, no embedding-model load, no database
query. Suitable for a container orchestrator's liveness probe (restart
the process if this fails) — see docker-compose.yml's ``backend``
healthcheck.

``GET /health/ready`` — "Can this backend currently perform normal
CodeGraph operations?" Reports every dependency's state via the
centralized app.core.dependencies.status_service (never duplicated health
logic per endpoint). A single dependency being down is reported as
"degraded", not as a process failure — see ``GET /health`` below, kept
for backward compatibility with existing callers/tests and the
docker-compose healthcheck predating this split.
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.dependencies.models import DependencyState, ReadinessReport
from app.core.dependencies.status_service import get_readiness_report
from app.graph.neo4j_client import get_neo4j_client
from app.indexing.chroma_store import get_vector_store
from app.indexing.sentence_transformer_provider import get_embedding_provider

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: str
    service: str


class DependencyStateResponse(BaseModel):
    status: str
    detail: str | None = None
    # Only populated for "llm"/"embedding_provider" — see DependencyState.
    model: str | None = None
    provider: str | None = None

    @classmethod
    def from_state(cls, state: DependencyState) -> "DependencyStateResponse":
        return cls(
            status=state.status.value,
            detail=state.detail,
            model=state.model,
            provider=state.provider,
        )


class ReadinessResponse(BaseModel):
    status: str
    dependencies: dict[str, DependencyStateResponse]

    @classmethod
    def from_report(cls, report: ReadinessReport) -> "ReadinessResponse":
        return cls(
            status=report.status,
            dependencies={
                name: DependencyStateResponse.from_state(state)
                for name, state in report.dependencies.items()
            },
        )


@router.get("/health/live", response_model=LivenessResponse)
async def get_liveness() -> LivenessResponse:
    return LivenessResponse(status="ok", service="codegraph-api")


@router.get("/health/ready", response_model=ReadinessResponse)
async def get_readiness(response: Response) -> ReadinessResponse:
    report = get_readiness_report(
        engine=get_engine(),
        neo4j_client=get_neo4j_client(),
        vector_store=get_vector_store(),
        embedding_provider=get_embedding_provider(),
        settings=get_settings(),
    )
    # 200 for ready/degraded (the process can still serve most requests —
    # callers should inspect `dependencies`), 503 only when nothing works.
    if report.status == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse.from_report(report)


# --- legacy combined endpoint (see this module's docstring) ----------------


class HealthResponse(BaseModel):
    status: str
    service: str
    dependencies: dict[str, str]
    embedding_provider: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    neo4j_status = get_neo4j_client().health_status()
    chroma_status = get_vector_store().health_check()

    provider = get_embedding_provider()
    embedding_info = {
        "model_name": provider.model_name,
        "status": "loaded" if provider.is_loaded() else "not_loaded",
    }

    overall_status = "ok" if neo4j_status == "ok" and chroma_status == "ok" else "degraded"
    return HealthResponse(
        status=overall_status,
        service="codegraph-api",
        dependencies={"neo4j": neo4j_status, "chromadb": chroma_status},
        embedding_provider=embedding_info,
    )

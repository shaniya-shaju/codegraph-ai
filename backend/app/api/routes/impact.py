"""Deterministic change-impact-analysis endpoints.

See ARCHITECTURE.md "Change-impact-analysis design". The deterministic
``GET .../impact/{symbol_id}`` endpoint works completely without an LLM;
the optional ``POST .../impact/{symbol_id}/explain`` endpoint only
describes an already-computed deterministic result in plain language and
can never add to it (see app.impact.explanation).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import (
    AmbiguousSymbolApiError,
    GraphUnavailableError,
    NotFoundError,
    SymbolNotFoundApiError,
    ValidationError,
)
from app.domain.impact.models import ImpactAnalysisResult
from app.domain.repositories.store import get_repository
from app.graph.exceptions import GraphError, Neo4jConnectionError
from app.graph.neo4j_client import Neo4jClient, get_neo4j_client
from app.impact import service as impact_service
from app.impact.exceptions import AmbiguousTargetError, ImpactError, TargetSymbolNotFoundError
from app.impact.explanation import ImpactExplanation, explain_impact
from app.rag.exceptions import LLMAnalysisError
from app.rag.llm_provider import AnswerLLMProvider, get_answer_llm_provider

router = APIRouter(tags=["impact"])

T = TypeVar("T")


def _require_repository(repository_id: str, db: Session = Depends(get_db)) -> str:
    if get_repository(db, repository_id) is None:
        raise NotFoundError(f"No repository with id {repository_id} exists.")
    return repository_id


def _graph_client() -> Neo4jClient:
    return get_neo4j_client()


def _llm_provider() -> AnswerLLMProvider:
    return get_answer_llm_provider()


def _ambiguous_message(exc: AmbiguousTargetError) -> str:
    candidates = "\n".join(f"- {c}" for c in exc.candidates)
    return f"{exc}\n\nCandidates:\n{candidates}"


def _run(fn: Callable[..., T], *args: object, **kwargs: object) -> T:  # noqa: UP047
    """Translate impact/graph-layer-internal exceptions into HTTP-facing AppErrors."""
    try:
        return fn(*args, **kwargs)
    except AmbiguousTargetError as exc:
        raise AmbiguousSymbolApiError(
            _ambiguous_message(exc), details={"candidates": exc.candidates}
        ) from exc
    except TargetSymbolNotFoundError as exc:
        raise SymbolNotFoundApiError(str(exc)) from exc
    except ImpactError as exc:
        raise ValidationError(str(exc)) from exc
    except Neo4jConnectionError as exc:
        raise GraphUnavailableError("The knowledge graph is temporarily unavailable.") from exc
    except GraphError as exc:
        raise GraphUnavailableError(f"The graph query failed: {exc}") from exc


@router.get("/repositories/{repository_id}/impact/{symbol_id}", response_model=ImpactAnalysisResult)
def get_impact_analysis(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    # Preferred lookup key (unambiguous — see "Symbol ID should be
    # preferred"). If `qualified_name` is also given, it takes priority
    # and `symbol_id` may be any non-empty placeholder in that case.
    qualified_name: str | None = Query(default=None),
    max_depth: int | None = Query(default=None, ge=1),
    max_nodes: int | None = Query(default=None, ge=1),
    include_downstream: bool = Query(default=True),
    include_tests: bool = Query(default=True),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> ImpactAnalysisResult:
    return _run(
        impact_service.get_impact_analysis,
        client,
        settings,
        repository_id=repository_id,
        symbol_id=None if qualified_name else symbol_id,
        qualified_name=qualified_name,
        max_depth=max_depth,
        max_nodes=max_nodes,
        include_downstream=include_downstream,
        include_tests=include_tests,
    )


@dataclass(frozen=True)
class ImpactExplanationResponse:
    result: ImpactAnalysisResult
    explanation: str
    warnings: list[str]


@router.post(
    "/repositories/{repository_id}/impact/{symbol_id}/explain",
    response_model=ImpactExplanationResponse,
)
async def explain_impact_analysis(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    qualified_name: str | None = Query(default=None),
    max_depth: int | None = Query(default=None, ge=1),
    max_nodes: int | None = Query(default=None, ge=1),
    include_downstream: bool = Query(default=True),
    include_tests: bool = Query(default=True),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
    llm_provider: AnswerLLMProvider = Depends(_llm_provider),
) -> ImpactExplanationResponse:
    result = _run(
        impact_service.get_impact_analysis,
        client,
        settings,
        repository_id=repository_id,
        symbol_id=None if qualified_name else symbol_id,
        qualified_name=qualified_name,
        max_depth=max_depth,
        max_nodes=max_nodes,
        include_downstream=include_downstream,
        include_tests=include_tests,
    )
    try:
        explanation: ImpactExplanation = await explain_impact(
            llm_provider, result, timeout_seconds=settings.llm_timeout_seconds
        )
    except LLMAnalysisError as exc:
        raise ValidationError(f"Could not generate an explanation: {exc}") from exc

    return ImpactExplanationResponse(
        result=result, explanation=explanation.explanation, warnings=explanation.warnings
    )

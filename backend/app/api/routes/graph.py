"""Repository knowledge-graph read endpoints.

Extends API_SPEC.md's repository contract with bounded, repository-scoped
graph queries — see ARCHITECTURE.md and DATA_MODEL.md. No endpoint here
accepts arbitrary Cypher, an arbitrary relationship name, or an unbounded
traversal (see SECURITY.md "Security requirements").
"""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import GraphUnavailableError, InvalidTraversalParameterError, NotFoundError
from app.domain.graph.models import GraphNode, GraphStatistics, GraphSubgraph, SymbolSearchResult
from app.domain.repositories.store import get_repository
from app.graph import repository_graph_service as graph_service
from app.graph.exceptions import GraphError, Neo4jConnectionError, TraversalLimitExceededError
from app.graph.neo4j_client import Neo4jClient, get_neo4j_client

router = APIRouter(tags=["graph"])

T = TypeVar("T")


def _require_repository(repository_id: str, db: Session = Depends(get_db)) -> str:
    if get_repository(db, repository_id) is None:
        raise NotFoundError(f"No repository with id {repository_id} exists.")
    return repository_id


def _graph_client() -> Neo4jClient:
    return get_neo4j_client()


def _run(fn: Callable[..., T], *args: object, **kwargs: object) -> T:  # noqa: UP047 (py3.11-compatible TypeVar)
    """Translate graph-layer-internal exceptions into HTTP-facing AppErrors."""
    try:
        return fn(*args, **kwargs)
    except TraversalLimitExceededError as exc:
        raise InvalidTraversalParameterError(str(exc)) from exc
    except Neo4jConnectionError as exc:
        raise GraphUnavailableError("The knowledge graph is temporarily unavailable.") from exc
    except GraphError as exc:
        raise GraphUnavailableError(f"The graph query failed: {exc}") from exc


@router.get("/repositories/{repository_id}/graph", response_model=GraphSubgraph)
def get_repository_graph(
    *,
    repository_id: str = Depends(_require_repository),
    root_symbol_id: str | None = Query(default=None),
    depth: int | None = Query(default=None, ge=1),
    max_nodes: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> GraphSubgraph:
    if root_symbol_id:
        return _run(
            graph_service.get_symbol_neighbors,
            client,
            settings,
            repository_id=repository_id,
            symbol_id=root_symbol_id,
            depth=depth,
            limit=max_nodes,
        )
    return _run(
        graph_service.get_repository_overview,
        client,
        settings,
        repository_id=repository_id,
        depth=depth,
        limit=max_nodes,
    )


@router.get("/repositories/{repository_id}/graph/statistics", response_model=GraphStatistics)
def get_graph_statistics(
    *,
    repository_id: str = Depends(_require_repository),
    client: Neo4jClient = Depends(_graph_client),
) -> GraphStatistics:
    return _run(graph_service.get_statistics, client, repository_id=repository_id)


@router.get("/repositories/{repository_id}/symbols/search", response_model=list[SymbolSearchResult])
def search_symbols(
    *,
    repository_id: str = Depends(_require_repository),
    q: str = Query(min_length=1),
    symbol_type: str | None = Query(default=None),
    file_path: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> list[SymbolSearchResult]:
    return _run(
        graph_service.search_symbols,
        client,
        settings,
        repository_id=repository_id,
        query=q,
        symbol_type=symbol_type,
        file_path=file_path,
        limit=limit,
    )


@router.get("/repositories/{repository_id}/symbols/{symbol_id}", response_model=GraphNode)
def get_symbol(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    client: Neo4jClient = Depends(_graph_client),
) -> GraphNode:
    node = _run(graph_service.get_symbol, client, repository_id=repository_id, symbol_id=symbol_id)
    if node is None:
        raise NotFoundError(f"No symbol with id {symbol_id} exists in repository {repository_id}.")
    return node


@router.get(
    "/repositories/{repository_id}/symbols/{symbol_id}/neighbors", response_model=GraphSubgraph
)
def get_symbol_neighbors(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    depth: int | None = Query(default=None, ge=1),
    limit: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> GraphSubgraph:
    return _run(
        graph_service.get_symbol_neighbors,
        client,
        settings,
        repository_id=repository_id,
        symbol_id=symbol_id,
        depth=depth,
        limit=limit,
    )


@router.get(
    "/repositories/{repository_id}/symbols/{symbol_id}/callers", response_model=GraphSubgraph
)
def get_symbol_callers(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    limit: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> GraphSubgraph:
    return _run(
        graph_service.get_callers,
        client,
        settings,
        repository_id=repository_id,
        symbol_id=symbol_id,
        limit=limit,
    )


@router.get(
    "/repositories/{repository_id}/symbols/{symbol_id}/callees", response_model=GraphSubgraph
)
def get_symbol_callees(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    limit: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> GraphSubgraph:
    return _run(
        graph_service.get_callees,
        client,
        settings,
        repository_id=repository_id,
        symbol_id=symbol_id,
        limit=limit,
    )


@router.get(
    "/repositories/{repository_id}/symbols/{symbol_id}/dependencies", response_model=GraphSubgraph
)
def get_symbol_dependencies(
    symbol_id: str,
    *,
    repository_id: str = Depends(_require_repository),
    limit: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> GraphSubgraph:
    return _run(
        graph_service.get_dependencies,
        client,
        settings,
        repository_id=repository_id,
        symbol_id=symbol_id,
        limit=limit,
    )


@router.get("/repositories/{repository_id}/paths", response_model=GraphSubgraph)
def get_path_between_symbols(
    *,
    repository_id: str = Depends(_require_repository),
    source_symbol_id: str = Query(...),
    target_symbol_id: str = Query(...),
    max_depth: int | None = Query(default=None, ge=1),
    client: Neo4jClient = Depends(_graph_client),
    settings: Settings = Depends(get_settings),
) -> GraphSubgraph:
    return _run(
        graph_service.find_path,
        client,
        settings,
        repository_id=repository_id,
        source_symbol_id=source_symbol_id,
        target_symbol_id=target_symbol_id,
        max_depth=max_depth,
    )

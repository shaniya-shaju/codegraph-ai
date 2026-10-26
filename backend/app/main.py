"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, graph, health, impact, indexing, query, repositories, retrieval
from app.core.config import get_settings
from app.core.config_validation import check_configuration
from app.core.database import get_session_factory
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_context import request_id_middleware
from app.domain.repositories.models import RepositoryRecord
from app.graph.neo4j_client import get_neo4j_client
from app.graph.schema import ensure_schema

API_V1_PREFIX = "/api/v1"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Advisory only — logs clear warnings for an obviously-incomplete
    # configuration (missing LLM_BASE_URL, placeholder credentials, an
    # unwritable workspace dir, ...) without contacting any dependency or
    # blocking startup (see app/core/config_validation.py).
    check_configuration(get_settings())

    # Best-effort schema setup — Neo4j being briefly unreachable at boot
    # must not prevent the API (including /health, which reports Neo4j's
    # status) from starting. Per-request graph endpoints fail clearly
    # (503 GRAPH_UNAVAILABLE) if Neo4j is still down when they're called.
    try:
        ensure_schema(get_neo4j_client())
    except Exception:
        logger.warning(
            "Could not initialize Neo4j schema at startup; will retry lazily.", exc_info=True
        )

    yield

    try:
        get_neo4j_client().close()
    except Exception:
        logger.warning("Error while closing the Neo4j driver during shutdown.", exc_info=True)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="CodeGraph AI API",
        version="0.1.0",
        description=(
            "Graph-augmented RAG API for Python source-code understanding "
            "and change-impact analysis."
        ),
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Registered after CORSMiddleware so it runs closer to the actual
    # route handler (Starlette applies middleware in reverse registration
    # order) — every response, including CORS preflight rejections, still
    # gets an X-Request-ID.
    app.middleware("http")(request_id_middleware)

    register_exception_handlers(app)

    @app.middleware("http")
    async def enforce_auth_and_repository_ownership(request: Request, call_next):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path.startswith(f"{API_V1_PREFIX}/health")
            or path.startswith(f"{API_V1_PREFIX}/auth")
        ):
            return await call_next(request)
        if not path.startswith(API_V1_PREFIX):
            return await call_next(request)

        from app.api.routes.auth import UserRecord, validate_token

        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        user_id = validate_token(token) if token else None

        if not user_id:
            if os.environ.get("TESTING") == "1":
                user_id = "test-user-0000"
                session = get_session_factory()()
                try:
                    if session.get(UserRecord, user_id) is None:
                        session.add(
                            UserRecord(
                                user_id=user_id,
                                name="Test User",
                                email="test@example.com",
                                password_hash="test",
                            )
                        )
                        session.commit()
                finally:
                    session.close()
            else:
                return JSONResponse(
                    status_code=401, content={"detail": "Please log in to continue."}
                )

        session = get_session_factory()()
        try:
            if session.get(UserRecord, user_id) is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "This account is no longer available. Please log in again."},
                )
            parts = path.split("/")
            if (
                len(parts) >= 5
                and parts[3] == "repositories"
                and parts[4] not in {"upload", "clone"}
            ):
                repository_id = parts[4]
                record = session.get(RepositoryRecord, repository_id)
                if record is not None and record.owner_id != user_id:
                    from app.core.exceptions import NotFoundError

                    raise NotFoundError(f"Repository '{repository_id}' does not exist.")
            request.state.user_id = user_id
        finally:
            session.close()
        return await call_next(request)

    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(auth.router, prefix=API_V1_PREFIX)
    app.include_router(repositories.router, prefix=API_V1_PREFIX)
    app.include_router(graph.router, prefix=API_V1_PREFIX)
    app.include_router(indexing.router, prefix=API_V1_PREFIX)
    app.include_router(retrieval.router, prefix=API_V1_PREFIX)
    app.include_router(query.router, prefix=API_V1_PREFIX)
    app.include_router(impact.router, prefix=API_V1_PREFIX)

    return app


app = create_app()

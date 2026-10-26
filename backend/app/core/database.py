"""SQLAlchemy engine/session plumbing for application metadata.

This is deliberately generic (no repository-specific code) — see
DATA_MODEL.md "SQLite (→ PostgreSQL): application metadata". Table
definitions live with their domain (e.g. app.domain.repositories.models),
not here.
"""

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_SQLITE_PREFIX = "sqlite:///"


class Base(DeclarativeBase):
    """Declarative base shared by every SQLAlchemy model in the app."""


def _ensure_sqlite_directory_exists(database_url: str) -> None:
    if not database_url.startswith(_SQLITE_PREFIX):
        return
    db_path = database_url.removeprefix(_SQLITE_PREFIX)
    if db_path in ("", ":memory:"):
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_engine() -> Engine:
    """Cached engine accessor. Tests must call ``get_engine.cache_clear()``
    (alongside ``get_settings.cache_clear()``) after changing DATABASE_URL.
    """
    settings = get_settings()
    _ensure_sqlite_directory_exists(settings.database_url)
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all known tables if they don't already exist.

    No Alembic migrations yet (see AGENTS.md directory layout) — this is
    intentionally the whole bootstrap story for now.
    """
    Base.metadata.create_all(bind=get_engine())
    # Minimal forward migration for existing SQLite databases. Legacy rows
    # remain ownerless and are not exposed to any authenticated account.
    engine = get_engine()
    if "repositories" in inspect(engine).get_table_names():
        columns = {column["name"] for column in inspect(engine).get_columns("repositories")}
        if "owner_id" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE repositories ADD COLUMN owner_id VARCHAR NULL")
                )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped SQLAlchemy session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_database_state() -> None:
    """Clear cached engine/session-factory state.

    Test-only escape hatch: after changing DATABASE_URL via environment
    variables and clearing ``get_settings``'s cache, call this too so a
    fresh engine bound to the new URL is created on next use.
    """
    get_engine.cache_clear()
    get_session_factory.cache_clear()

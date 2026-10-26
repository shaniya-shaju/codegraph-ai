"""The indexing manifest: which chunk_ids are currently indexed for which
repository, with what content_hash and embedding_model.

See the indexing task's "Incremental indexing". Stored in the application
database (SQLAlchemy, same `Base`/engine as app.domain.repositories —
see core/database.py) rather than a separate store, since it's small,
relational, operational metadata exactly like the `repositories` table.

This is what makes reindexing skip unchanged chunks: indexing_service.py
compares a freshly-built chunk's (chunk_id, content_hash, embedding_model)
against this table before deciding whether to re-embed it, and deletes
whatever manifest rows (and vector-store documents) are no longer produced
by the current parse — see indexing_service.py.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IndexManifestEntry(Base):
    """One row per currently-indexed chunk. `chunk_id` is already a
    deterministic, globally-unique id (see hashing.py), so it's the
    primary key directly — no separate surrogate id needed."""

    __tablename__ = "indexing_manifest_entries"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    repository_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    symbol_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def get_manifest_for_repository(session: Session, repository_id: str) -> list[IndexManifestEntry]:
    statement = select(IndexManifestEntry).where(IndexManifestEntry.repository_id == repository_id)
    return list(session.scalars(statement))


def upsert_manifest_entry(
    session: Session,
    *,
    chunk_id: str,
    repository_id: str,
    file_path: str,
    symbol_id: str | None,
    content_hash: str,
    embedding_model: str,
) -> None:
    existing = session.get(IndexManifestEntry, chunk_id)
    if existing is not None:
        existing.repository_id = repository_id
        existing.file_path = file_path
        existing.symbol_id = symbol_id
        existing.content_hash = content_hash
        existing.embedding_model = embedding_model
        existing.indexed_at = _utcnow()
    else:
        session.add(
            IndexManifestEntry(
                chunk_id=chunk_id,
                repository_id=repository_id,
                file_path=file_path,
                symbol_id=symbol_id,
                content_hash=content_hash,
                embedding_model=embedding_model,
                indexed_at=_utcnow(),
            )
        )


def delete_manifest_entries(session: Session, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    session.execute(delete(IndexManifestEntry).where(IndexManifestEntry.chunk_id.in_(chunk_ids)))


def delete_manifest_for_repository(session: Session, repository_id: str) -> None:
    session.execute(
        delete(IndexManifestEntry).where(IndexManifestEntry.repository_id == repository_id)
    )

"""Repository-pattern data access for RepositoryRecord.

Thin CRUD wrappers only — no ingestion logic (that lives in
app.ingestion.service), no HTTP concerns (that lives in
app.api.routes.repositories).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.repositories.models import RepositoryRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_repository(
    session: Session,
    *,
    repository_id: str,
    name: str,
    source_type: str,
    source_location: str,
    default_branch: str | None = None,
) -> RepositoryRecord:
    record = RepositoryRecord(
        repository_id=repository_id,
        name=name,
        source_type=source_type,
        source_location=source_location,
        default_branch=default_branch,
        status="pending",
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_repository(session: Session, repository_id: str) -> RepositoryRecord | None:
    return session.get(RepositoryRecord, repository_id)


def list_repositories(session: Session) -> list[RepositoryRecord]:
    statement = select(RepositoryRecord).order_by(RepositoryRecord.created_at.desc())
    return list(session.scalars(statement))


def mark_ready(
    session: Session,
    record: RepositoryRecord,
    *,
    file_count: int,
    commit_sha: str | None = None,
    default_branch: str | None = None,
) -> RepositoryRecord:
    record.status = "ready"
    record.file_count = file_count
    if commit_sha is not None:
        record.commit_sha = commit_sha
    if default_branch is not None:
        record.default_branch = default_branch
    record.last_indexed_at = _utcnow()
    session.commit()
    session.refresh(record)
    return record


def mark_failed(
    session: Session, record: RepositoryRecord, *, error_message: str
) -> RepositoryRecord:
    record.status = "failed"
    record.error_message = error_message
    session.commit()
    session.refresh(record)
    return record

"""SQLAlchemy ORM model for the `repositories` table.

See DATA_MODEL.md "SQLite (→ PostgreSQL): application metadata". Extends
the documented columns with `commit_sha`, needed to satisfy "save branch
and commit information" for git-cloned repositories.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _new_repository_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RepositoryRecord(Base):
    """One imported repository (via ZIP upload or git clone)."""

    __tablename__ = "repositories"

    repository_id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_repository_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Null for pre-auth legacy records; deliberately inaccessible until migrated
    # by an administrator.
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # "zip_upload" | "git_url" (DATA_MODEL.md also documents "local_path",
    # not implemented by this change).
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_location: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    # "pending" | "cloning" | "extracting" | "ready" | "failed"
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

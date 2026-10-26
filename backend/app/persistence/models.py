"""``RepositoryAnalysisState`` — the persisted, explicit per-subsystem
analysis-readiness record the frontend (and this backend's own APIs) can
consume, see the integration-reliability task's "Database persistence".

Lives in ``app.persistence`` (a dedicated package for cross-cutting
operational-state tables, distinct from ``app.domain.repositories`` which
owns the repository *identity* record) per this task's own preferred
scope list. No Alembic migration is added: this project has no migration
tooling yet (see app.core.database.init_db's own docstring: "No Alembic
migrations yet... this is intentionally the whole bootstrap story for
now") — ``Base.metadata.create_all()`` picks up this new table
automatically and is backward compatible with an existing development
database (it only ever adds missing tables, never touches existing ones).
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.repositories.enums import AnalysisStage, OverallStatus, SubsystemStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RepositoryAnalysisState(Base):
    """One row per repository_id — always upserted in place (never one
    row per analysis run), so its ``updated_at``/subsystem fields always
    reflect the *latest* analysis attempt."""

    __tablename__ = "repository_analysis_state"

    repository_id: Mapped[str] = mapped_column(String, primary_key=True)

    parser_status: Mapped[str] = mapped_column(
        String, nullable=False, default=SubsystemStatus.NOT_STARTED.value
    )
    graph_status: Mapped[str] = mapped_column(
        String, nullable=False, default=SubsystemStatus.NOT_STARTED.value
    )
    vector_status: Mapped[str] = mapped_column(
        String, nullable=False, default=SubsystemStatus.NOT_STARTED.value
    )
    overall_status: Mapped[str] = mapped_column(
        String, nullable=False, default=OverallStatus.NOT_STARTED.value
    )

    current_stage: Mapped[str] = mapped_column(
        String, nullable=False, default=AnalysisStage.IMPORT.value
    )
    progress_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    job_id: Mapped[str | None] = mapped_column(String, nullable=True)

    files_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    graph_node_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_relationship_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vector_chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # JSON-encoded list[str] — see analysis_state_service.py's (de)serialization.
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    graph_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vector_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # A deterministic revision identifier for this repository's on-disk
    # content — commit_sha for git, a content hash for zip uploads (see
    # "For ZIP uploads where no Git commit exists, use repository/content
    # hash"). graph_/vector_ revision are set to this value once each
    # subsystem finishes rebuilding — if they differ from
    # repository_revision, that subsystem is STALE (see "Repository
    # currency").
    repository_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    graph_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    vector_revision: Mapped[str | None] = mapped_column(String, nullable=True)

    parse_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_build_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vector_index_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

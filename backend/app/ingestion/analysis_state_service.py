"""CRUD + derivation logic for ``RepositoryAnalysisState`` — see the
integration-reliability task's "Analysis orchestration": "The
orchestration service should own stage transitions. Individual
parser/graph/indexing components must not independently invent overall
repository states." This module is the ONLY place ``overall_status`` gets
computed; callers (the orchestrator) only ever report per-subsystem
outcomes.
"""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domain.repositories.enums import AnalysisStage, OverallStatus, SubsystemStatus
from app.persistence.models import RepositoryAnalysisState

# Deterministic progress allocation per stage — see "Analysis
# orchestration": "Exact percentages may differ, but must be deterministic
# and documented." (start_percent, end_percent) for each stage; progress
# within a stage is linearly interpolated by the caller when it knows a
# file-count fraction, or simply reported as the stage's end_percent
# otherwise.
STAGE_PROGRESS_RANGE: dict[AnalysisStage, tuple[float, float]] = {
    AnalysisStage.IMPORT: (0.0, 10.0),
    AnalysisStage.SCAN: (10.0, 20.0),
    AnalysisStage.PARSE: (20.0, 45.0),
    AnalysisStage.BUILD_GRAPH: (45.0, 70.0),
    AnalysisStage.BUILD_VECTOR_INDEX: (70.0, 95.0),
    AnalysisStage.FINALIZE: (95.0, 100.0),
    AnalysisStage.DONE: (100.0, 100.0),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _dump_list(items: list[str]) -> str:
    return json.dumps(items)


def _load_list(raw: str) -> list[str]:
    try:
        loaded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return loaded if isinstance(loaded, list) else []


def get_state(session: Session, repository_id: str) -> RepositoryAnalysisState | None:
    return session.get(RepositoryAnalysisState, repository_id)


def get_or_create_state(session: Session, repository_id: str) -> RepositoryAnalysisState:
    state = get_state(session, repository_id)
    if state is not None:
        return state
    state = RepositoryAnalysisState(repository_id=repository_id)
    session.add(state)
    session.commit()
    session.refresh(state)
    return state


def warnings_of(state: RepositoryAnalysisState) -> list[str]:
    return _load_list(state.warnings_json)


def errors_of(state: RepositoryAnalysisState) -> list[str]:
    return _load_list(state.errors_json)


def start_run(
    session: Session, repository_id: str, *, job_id: str, files_total: int | None = None
) -> RepositoryAnalysisState:
    """A fresh analysis run begins — resets per-run fields (warnings,
    errors, progress) but keeps the previous run's last-known-good
    counts/timestamps until this run actually overwrites them."""
    state = get_or_create_state(session, repository_id)
    state.job_id = job_id
    state.overall_status = OverallStatus.RUNNING.value
    state.parser_status = SubsystemStatus.PENDING.value
    state.graph_status = SubsystemStatus.NOT_STARTED.value
    state.vector_status = SubsystemStatus.NOT_STARTED.value
    state.current_stage = AnalysisStage.IMPORT.value
    state.progress_percentage = STAGE_PROGRESS_RANGE[AnalysisStage.IMPORT][0]
    state.files_total = files_total
    state.files_processed = 0
    state.files_failed = 0
    state.warnings_json = _dump_list([])
    state.errors_json = _dump_list([])
    state.started_at = _utcnow()
    state.completed_at = None
    state.updated_at = _utcnow()
    session.commit()
    session.refresh(state)
    return state


def update_stage(
    session: Session,
    repository_id: str,
    *,
    stage: AnalysisStage,
    progress_percentage: float | None = None,
    files_processed: int | None = None,
    files_total: int | None = None,
) -> RepositoryAnalysisState:
    state = get_or_create_state(session, repository_id)
    previously_stored = state.progress_percentage
    state.current_stage = stage.value
    _start, end = STAGE_PROGRESS_RANGE[stage]
    candidate = progress_percentage if progress_percentage is not None else end
    # Progress must never decrease within one run (see "Progress must
    # never decrease.") — clamp against whatever was already stored
    # before this call, not just this stage's own range.
    state.progress_percentage = max(candidate, previously_stored)
    if files_processed is not None:
        state.files_processed = files_processed
    if files_total is not None:
        state.files_total = files_total
    state.updated_at = _utcnow()
    session.commit()
    session.refresh(state)
    return state


def mark_parser_result(
    session: Session,
    repository_id: str,
    *,
    status: SubsystemStatus,
    files_total: int,
    files_processed: int,
    files_failed: int,
    duration_ms: int | None = None,
    error: str | None = None,
) -> RepositoryAnalysisState:
    state = get_or_create_state(session, repository_id)
    state.parser_status = status.value
    state.files_total = files_total
    state.files_processed = files_processed
    state.files_failed = files_failed
    if duration_ms is not None:
        state.parse_duration_ms = duration_ms
    if error:
        _append_error(state, error)
    state.updated_at = _utcnow()
    session.commit()
    session.refresh(state)
    return state


def mark_graph_result(
    session: Session,
    repository_id: str,
    *,
    status: SubsystemStatus,
    node_count: int | None = None,
    relationship_count: int | None = None,
    duration_ms: int | None = None,
    revision: str | None = None,
    warning: str | None = None,
    error: str | None = None,
) -> RepositoryAnalysisState:
    state = get_or_create_state(session, repository_id)
    state.graph_status = status.value
    if node_count is not None:
        state.graph_node_count = node_count
    if relationship_count is not None:
        state.graph_relationship_count = relationship_count
    if duration_ms is not None:
        state.graph_build_duration_ms = duration_ms
    if status is SubsystemStatus.READY:
        state.graph_revision = revision
        state.graph_updated_at = _utcnow()
    if warning:
        _append_warning(state, warning)
    if error:
        _append_error(state, error)
    state.updated_at = _utcnow()
    session.commit()
    session.refresh(state)
    return state


def mark_vector_result(
    session: Session,
    repository_id: str,
    *,
    status: SubsystemStatus,
    chunk_count: int | None = None,
    duration_ms: int | None = None,
    revision: str | None = None,
    warning: str | None = None,
    error: str | None = None,
) -> RepositoryAnalysisState:
    state = get_or_create_state(session, repository_id)
    state.vector_status = status.value
    if chunk_count is not None:
        state.vector_chunk_count = chunk_count
    if duration_ms is not None:
        state.vector_index_duration_ms = duration_ms
    if status is SubsystemStatus.READY:
        state.vector_revision = revision
        state.vector_updated_at = _utcnow()
    if warning:
        _append_warning(state, warning)
    if error:
        _append_error(state, error)
    state.updated_at = _utcnow()
    session.commit()
    session.refresh(state)
    return state


def _append_warning(state: RepositoryAnalysisState, message: str) -> None:
    warnings = _load_list(state.warnings_json)
    warnings.append(message)
    state.warnings_json = _dump_list(warnings)


def _append_error(state: RepositoryAnalysisState, message: str) -> None:
    errors = _load_list(state.errors_json)
    errors.append(message)
    state.errors_json = _dump_list(errors)


def derive_overall_status(
    *, parser: SubsystemStatus, graph: SubsystemStatus, vector: SubsystemStatus
) -> OverallStatus:
    """The ONLY place overall_status is computed from subsystem statuses
    — see "Do not mark a repository fully READY if required graph or
    vector analysis failed." and this task's own worked examples."""
    if parser is SubsystemStatus.FAILED:
        return OverallStatus.FAILED
    if parser in (SubsystemStatus.NOT_STARTED, SubsystemStatus.PENDING, SubsystemStatus.RUNNING):
        return OverallStatus.RUNNING
    # parser is READY from here on.
    if graph is SubsystemStatus.RUNNING or vector is SubsystemStatus.RUNNING:
        return OverallStatus.RUNNING
    if graph is SubsystemStatus.STALE or vector is SubsystemStatus.STALE:
        return OverallStatus.STALE
    if graph is SubsystemStatus.FAILED or vector is SubsystemStatus.FAILED:
        return OverallStatus.PARTIAL
    if graph is SubsystemStatus.READY and vector is SubsystemStatus.READY:
        return OverallStatus.READY
    return OverallStatus.PARTIAL


def finalize_run(
    session: Session,
    repository_id: str,
    *,
    repository_revision: str | None,
    total_duration_ms: int | None = None,
) -> RepositoryAnalysisState:
    """``total_duration_ms`` is supplied by the caller (measured with
    ``time.monotonic()`` across the run — see app.ingestion.orchestrator)
    rather than computed here from ``started_at``/``completed_at``: SQLite's
    ``DateTime(timezone=True)`` columns round-trip as *naive* datetimes on
    read-back (no real timezone storage), which would make a
    ``completed_at - started_at`` subtraction against the tz-aware
    ``_utcnow()`` raise ``TypeError: can't subtract offset-naive and
    offset-aware datetimes`` — monotonic wall-clock timing sidesteps that
    entirely and is more correct for a duration measurement anyway."""
    state = get_or_create_state(session, repository_id)
    overall = derive_overall_status(
        parser=SubsystemStatus(state.parser_status),
        graph=SubsystemStatus(state.graph_status),
        vector=SubsystemStatus(state.vector_status),
    )
    state.overall_status = overall.value
    state.current_stage = AnalysisStage.DONE.value
    state.progress_percentage = 100.0
    state.repository_revision = repository_revision
    now = _utcnow()
    state.completed_at = now
    state.updated_at = now
    if total_duration_ms is not None:
        state.total_duration_ms = total_duration_ms
    session.commit()
    session.refresh(state)
    return state


def mark_run_failed(session: Session, repository_id: str, *, error: str) -> RepositoryAnalysisState:
    """The whole run aborted before parser/graph/vector could each report
    their own outcome (e.g. acquisition failed) — see "Parser catastrophic
    failure" example."""
    state = get_or_create_state(session, repository_id)
    state.parser_status = SubsystemStatus.FAILED.value
    state.graph_status = SubsystemStatus.NOT_STARTED.value
    state.vector_status = SubsystemStatus.NOT_STARTED.value
    state.overall_status = OverallStatus.FAILED.value
    state.current_stage = AnalysisStage.DONE.value
    _append_error(state, error)
    now = _utcnow()
    state.completed_at = now
    state.updated_at = now
    session.commit()
    session.refresh(state)
    return state


def check_and_mark_stale(
    session: Session, repository_id: str, *, current_repository_revision: str | None
) -> RepositoryAnalysisState | None:
    """Call with a freshly recomputed revision (e.g. from the current
    on-disk workspace) to detect drift since the last successful analysis
    — see "If repository content changes after analysis: graph_status =
    STALE / vector_status = STALE. Do not answer with stale data
    silently.". A no-op if there's no persisted state yet, no revision to
    compare, or the revision still matches."""
    state = get_state(session, repository_id)
    if state is None or current_repository_revision is None:
        return state
    if state.repository_revision == current_repository_revision:
        return state

    changed = False
    if state.graph_status == SubsystemStatus.READY.value:
        state.graph_status = SubsystemStatus.STALE.value
        changed = True
    if state.vector_status == SubsystemStatus.READY.value:
        state.vector_status = SubsystemStatus.STALE.value
        changed = True
    if changed:
        state.overall_status = derive_overall_status(
            parser=SubsystemStatus(state.parser_status),
            graph=SubsystemStatus(state.graph_status),
            vector=SubsystemStatus(state.vector_status),
        ).value
        state.updated_at = _utcnow()
        session.commit()
        session.refresh(state)
    return state


def is_current(state: RepositoryAnalysisState | None, repository_revision: str | None) -> bool:
    """True only when a previous run's overall status was READY *and* it
    was built from exactly this revision — the ``force=False`` skip
    condition for ``POST .../analyze`` (see "Repository currency")."""
    if state is None or repository_revision is None:
        return False
    return (
        state.overall_status == OverallStatus.READY.value
        and state.repository_revision == repository_revision
    )


def graph_current(state: RepositoryAnalysisState) -> bool:
    return (
        state.graph_status == SubsystemStatus.READY.value
        and state.graph_revision == state.repository_revision
    )


def vector_current(state: RepositoryAnalysisState) -> bool:
    return (
        state.vector_status == SubsystemStatus.READY.value
        and state.vector_revision == state.repository_revision
    )


def delete_state(session: Session, repository_id: str) -> None:
    state = get_state(session, repository_id)
    if state is not None:
        session.delete(state)
        session.commit()

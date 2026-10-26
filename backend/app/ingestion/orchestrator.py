"""The central analysis orchestrator — see the integration-reliability
task's "Analysis orchestration": "The orchestration service should own
stage transitions. Individual parser/graph/indexing components must not
independently invent overall repository states."

Pipeline: IMPORT -> SCAN -> PARSE -> BUILD_GRAPH -> BUILD_VECTOR_INDEX ->
FINALIZE (see app.domain.repositories.enums.AnalysisStage and
app.ingestion.analysis_state_service.STAGE_PROGRESS_RANGE for the
deterministic progress allocation). Every stage transition is persisted
via app.ingestion.analysis_state_service (the durable source of truth)
and broadcast via app.ingestion.progress (best-effort, live-subscriber-only).

This module is used by BOTH the synchronous initial-import flow
(app.ingestion.service, called inline from the upload/clone request) and
the standalone ``POST /repositories/{id}/analyze`` endpoint (run in a
background thread — see ``submit_background_analysis`` — since this
project has no worker queue yet; see AGENTS.md rule 9). Both paths funnel
through the same ``run_analysis`` so there is exactly one place that
decides overall repository state.
"""

import contextlib
import hashlib
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.code_symbols.models import ParsedFile
from app.domain.repositories.enums import AnalysisStage, SubsystemStatus
from app.domain.repositories.models import RepositoryRecord
from app.graph import repository_graph_service
from app.graph.exceptions import GraphError
from app.graph.graph_builder import RepositoryMetadata, build_repository_graph
from app.graph.neo4j_client import Neo4jClient
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.exceptions import IndexingError
from app.indexing.indexing_service import index_repository
from app.indexing.vector_store import VectorStore
from app.ingestion import analysis_state_service as state_service
from app.ingestion.analysis import parse_repository_files
from app.ingestion.progress import AnalysisProgressEvent, get_broadcaster
from app.persistence.models import RepositoryAnalysisState

logger = logging.getLogger(__name__)

_STAGE_MESSAGES: dict[AnalysisStage, str] = {
    AnalysisStage.IMPORT: "Importing repository...",
    AnalysisStage.SCAN: "Scanning files...",
    AnalysisStage.PARSE: "Parsing Python...",
    AnalysisStage.BUILD_GRAPH: "Building knowledge graph...",
    AnalysisStage.BUILD_VECTOR_INDEX: "Generating embeddings...",
    AnalysisStage.FINALIZE: "Finalizing...",
    AnalysisStage.DONE: "Done.",
}


def compute_repository_revision(record: RepositoryRecord, parsed_files: list[ParsedFile]) -> str:
    """A deterministic revision id for the currently-on-disk repository
    content — see "Repository currency": "For ZIP uploads where no Git
    commit exists, use repository/content hash or equivalent deterministic
    analysis revision." Git-cloned repositories use their real commit sha
    directly (cheaper and more meaningful than a recomputed content hash)."""
    if record.source_type == "git_url" and record.commit_sha:
        return record.commit_sha
    digest = hashlib.sha256()
    for parsed_file in sorted(parsed_files, key=lambda pf: pf.file_path):
        digest.update(parsed_file.file_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(parsed_file.content_hash.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _emit(
    session: Session,
    *,
    repository_id: str,
    job_id: str,
    stage: AnalysisStage,
    progress_percentage: float | None = None,
    files_processed: int | None = None,
    files_total: int | None = None,
) -> RepositoryAnalysisState:
    state = state_service.update_stage(
        session,
        repository_id,
        stage=stage,
        progress_percentage=progress_percentage,
        files_processed=files_processed,
        files_total=files_total,
    )
    get_broadcaster().publish(
        AnalysisProgressEvent(
            repository_id=repository_id,
            job_id=job_id,
            stage=stage.value,
            status=state.overall_status,
            progress_percentage=state.progress_percentage,
            message=_STAGE_MESSAGES.get(stage),
            files_processed=state.files_processed,
            files_total=state.files_total,
        )
    )
    return state


def run_analysis(
    session: Session,
    settings: Settings,
    *,
    record: RepositoryRecord,
    workspace: Path,
    job_id: str,
    neo4j_client: Neo4jClient,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    force: bool = False,
) -> RepositoryAnalysisState:
    """Run the full IMPORT -> ... -> FINALIZE pipeline for one repository,
    persisting state at every stage. Never raises for a graph/vector
    failure (each subsystem's failure is independent — see
    app.ingestion.service's module docstring, unchanged from before this
    task) — only a catastrophic failure before parsing even completes
    propagates, so the caller can decide whether the whole import failed.
    """
    repository_id = record.repository_id
    run_started = time.monotonic()

    # Fast path: a git-sourced repository whose commit hasn't changed
    # needs no work at all (see "If analysis is already current and
    # force=false, do not perform unnecessary rebuilding.").
    if not force and record.source_type == "git_url" and record.commit_sha:
        existing = state_service.get_state(session, repository_id)
        if state_service.is_current(existing, record.commit_sha):
            assert existing is not None
            return existing

    state_service.start_run(session, repository_id, job_id=job_id)
    _emit(session, repository_id=repository_id, job_id=job_id, stage=AnalysisStage.IMPORT)

    _emit(session, repository_id=repository_id, job_id=job_id, stage=AnalysisStage.SCAN)

    parse_started = time.monotonic()
    parsed_files, line_counts = parse_repository_files(workspace, repository_id)
    parse_duration_ms = int((time.monotonic() - parse_started) * 1000)

    state_service.mark_parser_result(
        session,
        repository_id,
        status=SubsystemStatus.READY,
        files_total=len(parsed_files),
        files_processed=len(parsed_files),
        files_failed=0,
        duration_ms=parse_duration_ms,
    )
    _emit(
        session,
        repository_id=repository_id,
        job_id=job_id,
        stage=AnalysisStage.PARSE,
        files_processed=len(parsed_files),
        files_total=len(parsed_files),
    )

    repository_revision = compute_repository_revision(record, parsed_files)
    existing_state = state_service.get_state(session, repository_id)
    skip_rebuild = not force and state_service.is_current(existing_state, repository_revision)

    if skip_rebuild:
        assert existing_state is not None
        state_service.mark_graph_result(
            session, repository_id, status=SubsystemStatus.READY, revision=repository_revision
        )
        state_service.mark_vector_result(
            session, repository_id, status=SubsystemStatus.READY, revision=repository_revision
        )
        logger.info(
            "Repository %s is already current at revision %s; skipping graph/vector rebuild.",
            repository_id,
            repository_revision,
        )
    else:
        _run_graph_stage(
            session,
            settings,
            record=record,
            parsed_files=parsed_files,
            line_counts=line_counts,
            repository_id=repository_id,
            job_id=job_id,
            neo4j_client=neo4j_client,
            repository_revision=repository_revision,
        )
        _run_vector_stage(
            session,
            settings,
            parsed_files=parsed_files,
            repository_id=repository_id,
            job_id=job_id,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            repository_revision=repository_revision,
        )

    _emit(session, repository_id=repository_id, job_id=job_id, stage=AnalysisStage.FINALIZE)
    total_duration_ms = int((time.monotonic() - run_started) * 1000)
    final_state = state_service.finalize_run(
        session,
        repository_id,
        repository_revision=repository_revision,
        total_duration_ms=total_duration_ms,
    )
    get_broadcaster().publish(
        AnalysisProgressEvent(
            repository_id=repository_id,
            job_id=job_id,
            stage=AnalysisStage.DONE.value,
            status=final_state.overall_status,
            progress_percentage=100.0,
            message=_STAGE_MESSAGES[AnalysisStage.DONE],
            files_processed=final_state.files_processed,
            files_total=final_state.files_total,
        )
    )
    return final_state


def _run_graph_stage(
    session: Session,
    settings: Settings,
    *,
    record: RepositoryRecord,
    parsed_files: list[ParsedFile],
    line_counts: dict[str, int],
    repository_id: str,
    job_id: str,
    neo4j_client: Neo4jClient,
    repository_revision: str,
) -> None:
    _emit(session, repository_id=repository_id, job_id=job_id, stage=AnalysisStage.BUILD_GRAPH)
    started = time.monotonic()
    metadata = RepositoryMetadata(
        repository_id=repository_id,
        name=record.name,
        source_type=record.source_type,
        source_url=record.source_location if record.source_type == "git_url" else None,
        default_branch=record.default_branch,
        commit_hash=record.commit_sha,
        parser_version=parsed_files[0].parser_version if parsed_files else "0",
    )
    try:
        build_repository_graph(neo4j_client, metadata, parsed_files, line_counts)
        duration_ms = int((time.monotonic() - started) * 1000)
        node_count: int | None
        relationship_count: int | None
        try:
            stats = repository_graph_service.get_statistics(
                neo4j_client, repository_id=repository_id
            )
            node_count = sum(stats.node_counts.values())
            relationship_count = sum(stats.relationship_counts.values())
        except GraphError:
            node_count = relationship_count = None
        state_service.mark_graph_result(
            session,
            repository_id,
            status=SubsystemStatus.READY,
            node_count=node_count,
            relationship_count=relationship_count,
            duration_ms=duration_ms,
            revision=repository_revision,
        )
    except GraphError as exc:
        logger.warning(
            "Graph build failed for repository %s; files were still imported and scanned: %s",
            repository_id,
            exc,
        )
        state_service.mark_graph_result(
            session, repository_id, status=SubsystemStatus.FAILED, error=str(exc)
        )


def _run_vector_stage(
    session: Session,
    settings: Settings,
    *,
    parsed_files: list[ParsedFile],
    repository_id: str,
    job_id: str,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    repository_revision: str,
) -> None:
    _emit(
        session, repository_id=repository_id, job_id=job_id, stage=AnalysisStage.BUILD_VECTOR_INDEX
    )
    try:
        stats = index_repository(
            session,
            settings,
            embedding_provider,
            vector_store,
            repository_id=repository_id,
            parsed_files=parsed_files,
        )
        state_service.mark_vector_result(
            session,
            repository_id,
            status=SubsystemStatus.READY,
            chunk_count=stats.chunk_count,
            duration_ms=stats.duration_ms,
            revision=repository_revision,
        )
    except IndexingError as exc:
        logger.warning(
            "Vector indexing failed for repository %s; files were still imported and scanned: %s",
            repository_id,
            exc,
        )
        state_service.mark_vector_result(
            session, repository_id, status=SubsystemStatus.FAILED, error=str(exc)
        )


# --- background execution for POST /repositories/{id}/analyze --------------
#
# No worker queue exists in this project yet (see AGENTS.md rule 9) — this
# is a small, in-process thread pool, not a durable job queue. A crashed
# backend process loses track of an in-flight background run (its
# persisted state stays RUNNING) — see this task's final report "Known
# limitations" for why a full job-heartbeat/recovery system is out of
# scope here.

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis")
_running_lock = threading.Lock()
_running_repository_ids: set[str] = set()


def is_running(repository_id: str) -> bool:
    with _running_lock:
        return repository_id in _running_repository_ids


def _try_acquire(repository_id: str) -> bool:
    with _running_lock:
        if repository_id in _running_repository_ids:
            return False
        _running_repository_ids.add(repository_id)
        return True


def _release(repository_id: str) -> None:
    with _running_lock:
        _running_repository_ids.discard(repository_id)


def submit_background_analysis(
    *,
    session_factory: Callable[[], Session],
    settings: Settings,
    record: RepositoryRecord,
    workspace: Path,
    neo4j_client: Neo4jClient,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    force: bool,
) -> tuple[str, bool]:
    """Returns ``(job_id, started)``. If this repository already has a
    background run in progress, returns its existing job_id with
    ``started=False`` instead of starting a second one — see "Concurrent
    analysis": "a second request should either: return the existing job."
    (the strategy chosen and documented here)."""
    repository_id = record.repository_id
    if not _try_acquire(repository_id):
        existing = state_service.get_state(session_factory(), repository_id)
        job_id = existing.job_id if existing and existing.job_id else "unknown"
        return job_id, False

    job_id = str(uuid.uuid4())

    def _worker() -> None:
        worker_session = session_factory()
        try:
            run_analysis(
                worker_session,
                settings,
                record=record,
                workspace=workspace,
                job_id=job_id,
                neo4j_client=neo4j_client,
                embedding_provider=embedding_provider,
                vector_store=vector_store,
                force=force,
            )
        except Exception:
            logger.exception("Background analysis failed for repository %s", repository_id)
            with contextlib.suppress(Exception):
                state_service.mark_run_failed(
                    worker_session, repository_id, error="Analysis failed unexpectedly."
                )
        finally:
            worker_session.close()
            _release(repository_id)

    _executor.submit(_worker)
    return job_id, True

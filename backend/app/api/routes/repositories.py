"""Repository import endpoints: ZIP upload, public git clone, analysis
status/trigger/streaming, and deletion.

Extends API_SPEC.md "Repository management" with two new synchronous
import endpoints (no background task queue exists yet — see AGENTS.md
rule 9). See SECURITY.md "Repository acquisition safety" for the safety
requirements every code path here upholds. Repository content is never
executed, imported, or run — only copied/cloned to disk and passively
scanned (see app.ingestion.scanner).

The analysis endpoints (see the integration-reliability task's "Analysis
status APIs" / "Analysis progress streaming") expose
``app.persistence.models.RepositoryAnalysisState`` — populated by the same
orchestrator (app.ingestion.orchestrator) that the synchronous
upload/clone endpoints above already run inline.
"""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db, get_session_factory, init_db
from app.core.exceptions import NotFoundError, ValidationError
from app.domain.repositories.enums import AnalysisStage, OverallStatus
from app.domain.repositories.models import RepositoryRecord
from app.domain.repositories.schemas import CloneRequest, LanguageStats, RepositoryResponse
from app.domain.repositories.store import get_repository, list_repositories
from app.graph.neo4j_client import Neo4jClient, get_neo4j_client
from app.indexing.chroma_store import get_vector_store
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.sentence_transformer_provider import get_embedding_provider
from app.indexing.vector_store import VectorStore
from app.ingestion import analysis_state_service as state_service
from app.ingestion import orchestrator
from app.ingestion.analysis import repository_workspace
from app.ingestion.deletion import delete_repository_everywhere
from app.ingestion.progress import AnalysisProgressEvent, get_broadcaster
from app.ingestion.scanner import FileScanResult
from app.ingestion.service import (
    RepositoryImportResult,
    import_git_repository,
    import_zip_repository,
)
from app.ingestion.source_reader import (
    SourceFileNotFoundError,
    SourceFileTooLargeError,
    UnsafePathError,
    read_source_snippet,
)
from app.persistence.models import RepositoryAnalysisState

router = APIRouter(tags=["repositories"])

# No Alembic migrations yet (see AGENTS.md directory layout) — this is the
# whole schema-bootstrap story until they exist.
init_db()


def _require_repository(repository_id: str, db: Session = Depends(get_db)) -> str:
    if get_repository(db, repository_id) is None:
        raise NotFoundError(f"No repository with id {repository_id} exists.")
    return repository_id


def _to_language_stats(scan: FileScanResult) -> LanguageStats:
    return LanguageStats(
        total_files=scan.total_files,
        total_bytes=scan.total_bytes,
        python_files=scan.python_file_count,
        binary_files_skipped=scan.binary_files_skipped,
        languages=scan.language_counts,
    )


def _record_to_response(
    record: RepositoryRecord, *, file_stats: LanguageStats | None = None
) -> RepositoryResponse:
    return RepositoryResponse(
        repository_id=record.repository_id,
        name=record.name,
        source_type=record.source_type,
        source_location=record.source_location,
        status=record.status,
        default_branch=record.default_branch,
        commit_sha=record.commit_sha,
        file_count=record.file_count,
        error_message=record.error_message,
        file_stats=file_stats,
        created_at=record.created_at,
        last_indexed_at=record.last_indexed_at,
    )


def _to_response(result: RepositoryImportResult) -> RepositoryResponse:
    return _record_to_response(result.record, file_stats=_to_language_stats(result.scan))


@router.get("/repositories", response_model=list[RepositoryResponse])
def list_repositories_endpoint(db: Session = Depends(get_db), request: Request = None) -> list[RepositoryResponse]:
    """Added by the frontend-integration task (Prompt 11) — the dashboard
    has no way to discover which repositories exist without this. Purely
    read-only, reuses the existing ``list_repositories`` store function
    (no new business logic) — see that task's "Backend compatibility
    fixes"."""
    user_id = getattr(request.state, "user_id", None) if request else None
    return [_record_to_response(record) for record in list_repositories(db) if user_id and record.owner_id == user_id]


@router.get("/repositories/{repository_id}", response_model=RepositoryResponse)
def get_repository_endpoint(
    *, repository_id: str = Depends(_require_repository), db: Session = Depends(get_db)
) -> RepositoryResponse:
    """Added by the frontend-integration task (Prompt 11) — the repository
    overview page needs a repository's own name/source/status independent
    of (and before) its analysis state. Reuses the existing
    ``get_repository`` store function."""
    record = get_repository(db, repository_id)
    assert record is not None  # guaranteed by _require_repository
    return _record_to_response(record)


@router.post("/repositories/upload", response_model=RepositoryResponse, status_code=201)
def upload_repository(
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    request: Request = None,
) -> RepositoryResponse:
    if not file.filename:
        raise ValidationError("An uploaded file must have a filename.")

    settings = get_settings()
    result = import_zip_repository(
        db,
        settings,
        name=name,
        filename=file.filename,
        file_obj=file.file,
    )
    result.record.owner_id = request.state.user_id
    db.commit()
    return _to_response(result)


@router.post("/repositories/clone", response_model=RepositoryResponse, status_code=201)
def clone_repository_endpoint(
    payload: CloneRequest,
    db: Session = Depends(get_db),
    request: Request = None,
) -> RepositoryResponse:
    settings = get_settings()
    result = import_git_repository(
        db,
        settings,
        name=payload.name,
        git_url=payload.git_url,
        branch=payload.branch,
    )
    result.record.owner_id = request.state.user_id
    db.commit()
    return _to_response(result)


# --- analysis state / trigger / streaming -----------------------------------


class AnalysisStateResponse(BaseModel):
    repository_id: str
    overall_status: str
    parser_status: str
    graph_status: str
    vector_status: str
    current_stage: str
    progress_percentage: float
    job_id: str | None
    files_total: int | None
    files_processed: int | None
    files_failed: int | None
    graph_node_count: int | None
    graph_relationship_count: int | None
    vector_chunk_count: int | None
    warnings: list[str]
    errors: list[str]
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    graph_updated_at: datetime | None
    vector_updated_at: datetime | None
    repository_revision: str | None
    graph_current: bool
    vector_current: bool
    parse_duration_ms: int | None
    graph_build_duration_ms: int | None
    vector_index_duration_ms: int | None
    total_duration_ms: int | None

    @classmethod
    def from_state(cls, state: RepositoryAnalysisState) -> "AnalysisStateResponse":
        return cls(
            repository_id=state.repository_id,
            overall_status=state.overall_status,
            parser_status=state.parser_status,
            graph_status=state.graph_status,
            vector_status=state.vector_status,
            current_stage=state.current_stage,
            progress_percentage=state.progress_percentage,
            job_id=state.job_id,
            files_total=state.files_total,
            files_processed=state.files_processed,
            files_failed=state.files_failed,
            graph_node_count=state.graph_node_count,
            graph_relationship_count=state.graph_relationship_count,
            vector_chunk_count=state.vector_chunk_count,
            warnings=state_service.warnings_of(state),
            errors=state_service.errors_of(state),
            started_at=state.started_at,
            updated_at=state.updated_at,
            completed_at=state.completed_at,
            graph_updated_at=state.graph_updated_at,
            vector_updated_at=state.vector_updated_at,
            repository_revision=state.repository_revision,
            graph_current=state_service.graph_current(state),
            vector_current=state_service.vector_current(state),
            parse_duration_ms=state.parse_duration_ms,
            graph_build_duration_ms=state.graph_build_duration_ms,
            vector_index_duration_ms=state.vector_index_duration_ms,
            total_duration_ms=state.total_duration_ms,
        )


@router.get("/repositories/{repository_id}/analysis", response_model=AnalysisStateResponse)
def get_analysis_state(
    *, repository_id: str = Depends(_require_repository), db: Session = Depends(get_db)
) -> AnalysisStateResponse:
    state = state_service.get_or_create_state(db, repository_id)
    return AnalysisStateResponse.from_state(state)


class AnalyzeRequest(BaseModel):
    force: bool = False


class AnalyzeResponse(BaseModel):
    job_id: str
    repository_id: str
    status: str  # "running" | "already_running" | "current"


@router.post("/repositories/{repository_id}/analyze", response_model=AnalyzeResponse)
def trigger_analysis(
    payload: AnalyzeRequest,
    *,
    repository_id: str = Depends(_require_repository),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    neo4j_client: Neo4jClient = Depends(get_neo4j_client),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    vector_store: VectorStore = Depends(get_vector_store),
) -> AnalyzeResponse:
    """Runs the full analysis pipeline in a background thread (no worker
    queue exists in this project yet — see AGENTS.md rule 9) and returns
    immediately. Concurrency strategy (see "Concurrent analysis" — one of
    two documented options, chosen here): a repository that already has a
    run in progress gets its *existing* job_id back with
    ``status="already_running"`` rather than a 409 — simpler for a caller
    that just wants to know "is it running and what's its id" without
    needing to handle a conflict error specially.
    """
    record = get_repository(db, repository_id)
    assert record is not None  # guaranteed by _require_repository

    if orchestrator.is_running(repository_id):
        existing = state_service.get_state(db, repository_id)
        job_id = existing.job_id if existing and existing.job_id else "unknown"
        return AnalyzeResponse(job_id=job_id, repository_id=repository_id, status="already_running")

    if not payload.force:
        state = state_service.get_state(db, repository_id)
        if (
            record.source_type == "git_url"
            and record.commit_sha
            and state_service.is_current(state, record.commit_sha)
        ):
            assert state is not None
            return AnalyzeResponse(
                job_id=state.job_id or "-", repository_id=repository_id, status="current"
            )

    workspace = repository_workspace(repository_id)
    if not workspace.exists():
        raise ValidationError(
            "This repository's workspace is no longer available on disk — "
            "reimport it (upload or clone) before analyzing."
        )

    job_id, started = orchestrator.submit_background_analysis(
        session_factory=get_session_factory(),
        settings=settings,
        record=record,
        workspace=workspace,
        neo4j_client=neo4j_client,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        force=payload.force,
    )
    return AnalyzeResponse(
        job_id=job_id,
        repository_id=repository_id,
        status="running" if started else "already_running",
    )


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


_TERMINAL_OVERALL = {
    OverallStatus.READY.value,
    OverallStatus.PARTIAL.value,
    OverallStatus.FAILED.value,
    OverallStatus.STALE.value,
}


@router.get("/repositories/{repository_id}/analysis/stream")
async def stream_analysis(
    request: Request,
    *,
    repository_id: str = Depends(_require_repository),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE progress stream — see "Analysis progress streaming":
    "Persisted state remains the source of truth... may miss historical
    intermediate events after reconnect; the frontend can always call the
    regular status endpoint." A client connecting mid-run (or after
    everything already finished) is sent the current persisted state
    immediately, so it never has to wait for the next live event to show
    something."""

    async def event_source() -> AsyncIterator[str]:
        state = state_service.get_or_create_state(db, repository_id)
        snapshot = AnalysisStateResponse.from_state(state).model_dump(mode="json")
        yield _sse_event("progress", snapshot)
        if state.overall_status in _TERMINAL_OVERALL:
            final_event = (
                "failed" if state.overall_status == OverallStatus.FAILED.value else "completed"
            )
            yield _sse_event(final_event, snapshot)
            return

        broadcaster = get_broadcaster()
        with broadcaster.subscribe(repository_id) as q:
            while True:
                if await request.is_disconnected():
                    return
                event: AnalysisProgressEvent | None = await asyncio.to_thread(
                    broadcaster.poll, q, timeout=1.0
                )
                if event is None:
                    continue
                yield _sse_event("progress", dataclasses.asdict(event))
                if event.stage == AnalysisStage.DONE.value:
                    final_event = (
                        "failed" if event.status == OverallStatus.FAILED.value else "completed"
                    )
                    yield _sse_event(final_event, dataclasses.asdict(event))
                    return

    return StreamingResponse(event_source(), media_type="text/event-stream")


# --- deletion ----------------------------------------------------------------


@router.delete("/repositories/{repository_id}", status_code=200)
def delete_repository_endpoint(
    *,
    repository_id: str = Depends(_require_repository),
    db: Session = Depends(get_db),
    neo4j_client: Neo4jClient = Depends(get_neo4j_client),
    vector_store: VectorStore = Depends(get_vector_store),
) -> dict[str, object]:
    result = delete_repository_everywhere(
        db, repository_id=repository_id, neo4j_client=neo4j_client, vector_store=vector_store
    )
    return {
        "repository_id": repository_id,
        "status": "deleted" if result.fully_cleaned else "partially_cleaned",
        "cleaned": result.cleaned_stores,
        "errors": result.errors,
    }


# --- source viewing ----------------------------------------------------------
#
# Added by the frontend-integration task (Prompt 11) — citations only
# carry file/line metadata, never source content (see app.rag.answer_models
# .CodeCitation), so there was no existing safe way for the source viewer
# to show highlighted code around a citation. Read-only; validated
# repository-relative path; bounded response size — see
# app.ingestion.source_reader.


class SourceSnippetResponse(BaseModel):
    repository_id: str
    file_path: str
    start_line: int
    end_line: int
    total_lines: int
    content: str
    truncated: bool


@router.get(
    "/repositories/{repository_id}/files/source", response_model=SourceSnippetResponse
)
def get_source_snippet(
    *,
    repository_id: str = Depends(_require_repository),
    path: str = Query(..., min_length=1, description="Repository-relative file path."),
    start_line: int | None = Query(default=None, ge=1),
    end_line: int | None = Query(default=None, ge=1),
) -> SourceSnippetResponse:
    try:
        snippet = read_source_snippet(
            repository_id, relative_path=path, start_line=start_line, end_line=end_line
        )
    except UnsafePathError as exc:
        raise ValidationError(str(exc)) from exc
    except SourceFileTooLargeError as exc:
        raise ValidationError(str(exc)) from exc
    except SourceFileNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc

    return SourceSnippetResponse(
        repository_id=repository_id,
        file_path=snippet.file_path,
        start_line=snippet.start_line,
        end_line=snippet.end_line,
        total_lines=snippet.total_lines,
        content=snippet.content,
        truncated=snippet.truncated,
    )

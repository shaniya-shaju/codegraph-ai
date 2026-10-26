"""Top-level orchestration for repository import (ZIP upload / git clone).

Owns the sequence: validate -> persist a pending record -> acquire content
-> scan -> parse -> build the knowledge graph -> generate embeddings ->
mark ready, or clean up and mark failed on any error. See ARCHITECTURE.md
"Repository ingestion flow", the graph-layer task's "Analysis
integration", and the indexing task's "Analysis-pipeline integration".

Job-stage progression (visible via RepositoryRecord.status, polled
mid-request-in-practice since this is all synchronous — see AGENTS.md
rule 9, no worker queue exists yet):

    pending -> scanning -> parsing -> building_graph ->
    generating_embeddings -> ready | failed

This intentionally keeps "ready"/"failed" as the terminal values already
used by every existing caller/test rather than renaming to the graph/
indexing tasks' literal "completed" — see the graph-layer task's final
report for why. "generating_embeddings" is this task's literal name for
that stage, kept as-is since nothing pre-existing depended on a different
name for it.

Graph-build and vector-indexing failures do not fail the whole import:
the repository's files were still successfully acquired and scanned,
which is a complete, useful outcome on its own — see the graph-layer
task's "Keep the analysis orchestration behind a service interface so it
can be moved to Celery or another worker later," which implies analysis
can fail/retry independently of acquisition. The repository is marked
ready with `error_message` noting whichever index (graph and/or vector)
is missing/stale; callers can confirm current state via
GET .../graph/statistics and GET .../index/statistics (see the indexing
task's "The repository must expose whether graph and vector indexes are
current" — exposed through those endpoints rather than a new status
column, since RepositoryRecord's schema is out of this task's allowed
scope to extend). Only acquisition-level failures (bad zip/URL, clone
timeout, scan error) fail the import itself.

Never executes, imports, or runs anything from the acquired repository —
see SECURITY.md "Parsing safety" and "Repository acquisition safety".
"""

import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AppError,
    GitCloningDisabledError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from app.domain.repositories.enums import OverallStatus
from app.domain.repositories.models import RepositoryRecord
from app.domain.repositories.store import create_repository, mark_failed, mark_ready
from app.graph.neo4j_client import get_neo4j_client
from app.indexing.chroma_store import get_vector_store
from app.indexing.sentence_transformer_provider import get_embedding_provider
from app.ingestion import analysis_state_service as state_service
from app.ingestion.git_clone import (
    clone_repository,
    validate_allowed_host,
    validate_public_https_url,
)
from app.ingestion.orchestrator import run_analysis
from app.ingestion.scanner import FileScanResult, scan_repository
from app.ingestion.workspace import allocate_workspace, cleanup_workspace
from app.ingestion.zip_import import extract_zip_safely, is_zip_filename, save_upload_within_limit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepositoryImportResult:
    record: RepositoryRecord
    scan: FileScanResult


def _set_status(session: Session, record: RepositoryRecord, status: str) -> None:
    record.status = status
    session.commit()


def _append_error_note(record: RepositoryRecord, note: str) -> None:
    record.error_message = f"{record.error_message} {note}" if record.error_message else note


def _analyze_repository(session: Session, record: RepositoryRecord, workspace: Path) -> None:
    """Parse every scanned Python file, (re-)build this repository's
    knowledge graph, then generate/refresh its vector index — delegates
    the actual stage-by-stage work to app.ingestion.orchestrator.run_analysis
    (the single place stage transitions and RepositoryAnalysisState are
    owned — see that module's docstring), keeping this function's own
    contract (never raises for a graph/vector-only failure; only a
    parse-level failure propagates) unchanged for existing callers/tests.
    ``record.error_message`` still gets a short human-readable note for
    backward compatibility with the RepositoryResponse.error_message
    field — the authoritative, structured detail lives in
    RepositoryAnalysisState.warnings/errors (see GET .../analysis)."""
    settings = get_settings()
    job_id = str(uuid.uuid4())
    state = run_analysis(
        session,
        settings,
        record=record,
        workspace=workspace,
        job_id=job_id,
        neo4j_client=get_neo4j_client(),
        embedding_provider=get_embedding_provider(),
        vector_store=get_vector_store(),
    )
    if state.overall_status in (OverallStatus.PARTIAL.value, OverallStatus.FAILED.value):
        for error in state_service.errors_of(state):
            _append_error_note(record, error)
        session.commit()


def import_zip_repository(
    session: Session,
    settings: Settings,
    *,
    name: str,
    filename: str,
    file_obj: IO[bytes],
) -> RepositoryImportResult:
    """Extract an uploaded ZIP archive into a new repository and scan it."""
    if not name or not name.strip():
        raise ValidationError("A repository name is required.")
    if not filename or not is_zip_filename(filename):
        raise UnsupportedMediaTypeError("Only .zip file uploads are supported.")

    repository_id = str(uuid.uuid4())
    record = create_repository(
        session,
        repository_id=repository_id,
        name=name.strip(),
        source_type="zip_upload",
        source_location=filename,
    )

    max_upload_bytes = settings.ingestion_max_upload_size_mb * 1024 * 1024
    max_extracted_bytes = settings.ingestion_max_repo_size_mb * 1024 * 1024
    workspace_root = Path(settings.ingestion_workspace_dir)
    workspace = workspace_root / repository_id

    try:
        workspace = allocate_workspace(workspace_root, repository_id)

        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            save_upload_within_limit(file_obj, tmp_path, max_bytes=max_upload_bytes)
            extract_zip_safely(tmp_path, workspace, max_extracted_bytes=max_extracted_bytes)
        finally:
            tmp_path.unlink(missing_ok=True)

        _set_status(session, record, "scanning")
        scan = scan_repository(workspace)
        _analyze_repository(session, record, workspace)
        record = mark_ready(session, record, file_count=scan.total_files)
        return RepositoryImportResult(record=record, scan=scan)
    except AppError as exc:
        cleanup_workspace(workspace)
        mark_failed(session, record, error_message=exc.message)
        raise
    except Exception as exc:
        cleanup_workspace(workspace)
        mark_failed(session, record, error_message=str(exc))
        raise


def import_git_repository(
    session: Session,
    settings: Settings,
    *,
    name: str,
    git_url: str,
    branch: str | None = None,
) -> RepositoryImportResult:
    """Shallow-clone a public HTTPS git repository and scan it.

    Only public HTTPS URLs on the configured host allow-list are
    supported (REPO_CLONE_ALLOWED_HOSTS, default github.com/gitlab.com —
    see SECURITY.md "Repository acquisition safety"). Private
    repositories and SSH URLs are never supported, regardless of
    configuration. The whole feature can be turned off via
    REPO_URL_CLONE_ENABLED, independent of ZIP/local-path ingestion.
    """
    if not settings.repo_url_clone_enabled:
        raise GitCloningDisabledError(
            "Cloning a repository from a URL is disabled on this server "
            "(REPO_URL_CLONE_ENABLED=false). Upload a ZIP file instead, "
            "or ask an administrator to enable it."
        )
    if not name or not name.strip():
        raise ValidationError("A repository name is required.")
    # Fail fast on an obviously-invalid/disallowed URL, before creating
    # any DB record — mirrors import_zip_repository's early filename check.
    validate_public_https_url(git_url)
    validate_allowed_host(git_url, settings.repo_clone_allowed_hosts_set)

    repository_id = str(uuid.uuid4())
    record = create_repository(
        session,
        repository_id=repository_id,
        name=name.strip(),
        source_type="git_url",
        source_location=git_url,
        default_branch=branch,
    )

    workspace_root = Path(settings.ingestion_workspace_dir)
    workspace_root.mkdir(parents=True, exist_ok=True)
    destination = workspace_root / repository_id

    try:
        cloned = clone_repository(
            git_url,
            destination=destination,
            branch=branch,
            timeout_seconds=settings.ingestion_clone_timeout_seconds,
            max_size_bytes=settings.ingestion_max_repo_size_mb * 1024 * 1024,
            depth=settings.repo_clone_depth,
            allowed_hosts=settings.repo_clone_allowed_hosts_set,
        )
        _set_status(session, record, "scanning")
        scan = scan_repository(cloned.path)

        # Set before _analyze_repository so the graph's Repository node
        # gets the real commit/branch (mark_ready below re-sets the same
        # values along with status="ready" — harmless, kept for clarity).
        record.commit_sha = cloned.commit_sha
        record.default_branch = cloned.branch
        session.commit()

        _analyze_repository(session, record, cloned.path)
        record = mark_ready(
            session,
            record,
            file_count=scan.total_files,
            commit_sha=cloned.commit_sha,
            default_branch=cloned.branch,
        )
        return RepositoryImportResult(record=record, scan=scan)
    except AppError as exc:
        cleanup_workspace(destination)
        mark_failed(session, record, error_message=exc.message)
        raise
    except Exception as exc:
        cleanup_workspace(destination)
        mark_failed(session, record, error_message=str(exc))
        raise

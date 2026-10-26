"""Shared analysis-pipeline helpers: scan -> parse (-> graph and/or index).

Used by both the initial import flow (app.ingestion.service, which builds
the graph *and* the vector index right after acquiring a repository) and
the standalone ``POST /repositories/{id}/index`` endpoint (which only
rebuilds the vector index for an already-imported repository — it never
re-clones/re-uploads and never touches the graph; see
api/routes/indexing.py).
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.code_symbols.models import ParsedFile
from app.domain.repositories.store import get_repository
from app.domain.retrieval.models import IndexingStatistics
from app.indexing.chroma_store import get_vector_store
from app.indexing.exceptions import IndexingError
from app.indexing.indexing_service import index_repository
from app.indexing.sentence_transformer_provider import get_embedding_provider
from app.ingestion.scanner import scan_repository
from app.parsing.registry import build_default_registry, parse_source_bytes


def repository_workspace(repository_id: str) -> Path:
    settings = get_settings()
    return Path(settings.ingestion_workspace_dir) / repository_id


def parse_repository_files(
    workspace: Path, repository_id: str
) -> tuple[list[ParsedFile], dict[str, int]]:
    """Scan + parse every Python file under `workspace`.

    Returns the parsed files and a file_path -> line_count map (needed by
    graph_builder.py's File.line_count, which — per rule 9 in the
    graph-layer task — isn't retained on ParsedFile itself).
    """
    registry = build_default_registry()
    scan = scan_repository(workspace)

    parsed_files: list[ParsedFile] = []
    line_counts: dict[str, int] = {}
    for scanned_file in scan.files:
        if not scanned_file.is_python:
            continue
        raw_bytes = (workspace / scanned_file.relative_path).read_bytes()
        parsed = parse_source_bytes(
            registry, raw_bytes, Path(scanned_file.relative_path), repository_id
        )
        if parsed is None:
            continue
        parsed_files.append(parsed)
        line_counts[parsed.file_path] = raw_bytes.count(b"\n") + 1

    return parsed_files, line_counts


def analyze_and_index_repository(
    session: Session, *, repository_id: str, force_reindex: bool = False
) -> IndexingStatistics:
    """Standalone reindex: re-scan/re-parse an already-imported
    repository's existing on-disk workspace and rebuild its vector index
    only (see this module's docstring)."""
    record = get_repository(session, repository_id)
    if record is None:
        raise IndexingError(f"No repository with id {repository_id} exists.")

    workspace = repository_workspace(repository_id)
    if not workspace.exists():
        raise IndexingError(
            "This repository's workspace is no longer available on disk — "
            "reimport it (upload or clone) before indexing."
        )

    parsed_files, _line_counts = parse_repository_files(workspace, repository_id)

    settings = get_settings()
    return index_repository(
        session,
        settings,
        get_embedding_provider(),
        get_vector_store(),
        repository_id=repository_id,
        parsed_files=parsed_files,
        force_reindex=force_reindex,
    )

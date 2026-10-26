"""Indexing orchestration: parsed files -> chunks -> embeddings -> Chroma
+ manifest, idempotently.

See the indexing task's "Indexing service" and "Incremental indexing".
Does not know about RepositoryRecord/analysis-job status strings — that's
app.ingestion.service's job, which calls `index_repository` and updates
status around it (same layering as app.graph.graph_builder).
"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.code_symbols.models import ParsedFile
from app.domain.retrieval.models import CodeChunk, IndexingStatistics
from app.indexing.chunker import build_chunks_for_file
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.exceptions import EmbeddingProviderError, VectorStoreError
from app.indexing.metadata import (
    delete_manifest_entries,
    delete_manifest_for_repository,
    get_manifest_for_repository,
    upsert_manifest_entry,
)
from app.indexing.models import ChunkingLimits
from app.indexing.vector_store import VectorStore

logger = logging.getLogger(__name__)


def _count_symbols(parsed_file: ParsedFile) -> int:
    count = len(parsed_file.functions)

    def visit(cls: object) -> None:
        nonlocal count
        count += 1
        count += len(cls.methods)  # type: ignore[attr-defined]
        for nested in cls.nested_classes:  # type: ignore[attr-defined]
            visit(nested)

    for cls in parsed_file.classes:
        visit(cls)
    return count


@dataclass
class _BatchOutcome:
    indexed: int = 0
    errors: int = 0


def index_repository(
    session: Session,
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    *,
    repository_id: str,
    parsed_files: list[ParsedFile],
    force_reindex: bool = False,
) -> IndexingStatistics:
    """Build this repository's chunks, embed/upsert whatever is new or
    changed, delete whatever is stale, and record it all in the manifest.

    Never marks a chunk as indexed in the manifest unless its embedding
    was actually generated *and* upserted successfully in the same batch
    (see the indexing task: "A failed indexing run must not incorrectly
    mark missing chunks as successfully indexed").
    """
    started = time.monotonic()
    limits = ChunkingLimits(
        max_characters=settings.code_chunk_max_characters,
        max_lines=settings.code_chunk_max_lines,
        context_lines=settings.code_chunk_context_lines,
    )
    model_name = embedding_provider.model_name

    all_chunks: list[CodeChunk] = []
    for parsed_file in parsed_files:
        all_chunks.extend(
            build_chunks_for_file(
                parsed_file, repository_id=repository_id, limits=limits, embedding_model=model_name
            )
        )

    existing_manifest = {
        entry.chunk_id: entry for entry in get_manifest_for_repository(session, repository_id)
    }

    to_embed: list[CodeChunk] = []
    skipped = 0
    for chunk in all_chunks:
        existing = existing_manifest.get(chunk.id)
        unchanged = (
            existing is not None
            and existing.content_hash == chunk.content_hash
            and existing.embedding_model == model_name
        )
        if unchanged and not force_reindex:
            skipped += 1
        else:
            to_embed.append(chunk)

    outcome = _BatchOutcome()
    dimension = embedding_provider.dimension
    batch_size = max(1, settings.indexing_batch_size)

    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        try:
            vectors = embedding_provider.embed_documents([chunk.content for chunk in batch])
            vector_store.upsert(repository_id, batch, vectors)
        except (EmbeddingProviderError, VectorStoreError) as exc:
            outcome.errors += len(batch)
            logger.error(
                "Indexing batch failed for repository %s (%d chunks): %s",
                repository_id,
                len(batch),
                exc,
            )
            continue

        for chunk in batch:
            upsert_manifest_entry(
                session,
                chunk_id=chunk.id,
                repository_id=repository_id,
                file_path=chunk.file_path,
                symbol_id=chunk.symbol_id,
                content_hash=chunk.content_hash,
                embedding_model=model_name,
            )
        session.commit()
        outcome.indexed += len(batch)
        if dimension is None:
            dimension = embedding_provider.dimension

    current_ids = {chunk.id for chunk in all_chunks}
    stale_ids = [chunk_id for chunk_id in existing_manifest if chunk_id not in current_ids]
    if stale_ids:
        vector_store.delete(repository_id, stale_ids)
        delete_manifest_entries(session, stale_ids)
        session.commit()

    duration_ms = int((time.monotonic() - started) * 1000)
    return IndexingStatistics(
        repository_id=repository_id,
        file_count=len(parsed_files),
        symbol_count=sum(_count_symbols(pf) for pf in parsed_files),
        chunk_count=len(all_chunks),
        indexed_chunk_count=outcome.indexed,
        skipped_chunk_count=skipped,
        deleted_stale_chunk_count=len(stale_ids),
        embedding_model=model_name,
        embedding_dimension=dimension,
        duration_ms=duration_ms,
        error_count=outcome.errors,
    )


def delete_repository_index(
    session: Session, vector_store: VectorStore, *, repository_id: str
) -> None:
    """Remove this repository's Chroma collection and manifest rows —
    never touches any other repository's data."""
    vector_store.delete_repository(repository_id)
    delete_manifest_for_repository(session, repository_id)
    session.commit()

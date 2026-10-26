"""Repository-scoped semantic retrieval.

Distance metric: every Chroma collection is created with
``hnsw:space="cosine"`` (see chroma_store.py), so the distance Chroma
returns is ``1 - cosine_similarity`` (0 = identical direction, up to 2 =
opposite). This service converts it to a ``score`` via ``1 - distance``,
clamped to ``[0, 1]`` — a **ranking signal only**, never a probability or
confidence value (see the indexing task's "Do not label a score as
probability or confidence").
"""

from typing import cast

from app.core.config import Settings
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import VectorSearchQuery, VectorSearchResult
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.exceptions import InvalidQueryError
from app.indexing.vector_store import VectorStore, VectorStoreMatch


def _distance_to_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance))


def _validate_top_k(top_k: int | None, settings: Settings) -> int:
    value = top_k if top_k is not None else settings.vector_default_top_k
    if value < 1 or value > settings.vector_max_top_k:
        raise InvalidQueryError(
            f"top_k must be between 1 and {settings.vector_max_top_k} (got {value})."
        )
    return value


def _build_where(query: VectorSearchQuery) -> dict[str, object]:
    where: dict[str, object] = {}

    chunk_type_values: set[str] = set()
    if query.chunk_types:
        chunk_type_values.update(chunk_type.value for chunk_type in query.chunk_types)
    if query.symbol_types:
        chunk_type_values.update(chunk_type.value for chunk_type in query.symbol_types)
    if chunk_type_values:
        values = sorted(chunk_type_values)
        where["chunk_type"] = values[0] if len(values) == 1 else values

    if query.file_paths:
        where["file_path"] = (
            query.file_paths[0] if len(query.file_paths) == 1 else list(query.file_paths)
        )

    return where


def _to_result(match: VectorStoreMatch, *, repository_id: str) -> VectorSearchResult:
    metadata = match.metadata
    chunk_type_value = str(metadata.get("chunk_type", ChunkType.FUNCTION.value))
    return VectorSearchResult(
        chunk_id=match.chunk_id,
        repository_id=repository_id,
        symbol_id=cast("str | None", metadata.get("symbol_id")),
        chunk_type=ChunkType(chunk_type_value),
        qualified_name=cast("str | None", metadata.get("qualified_name")),
        file_path=str(metadata.get("file_path", "")),
        start_line=cast(int, metadata.get("start_line", 0)),
        end_line=cast(int, metadata.get("end_line", 0)),
        content=match.content,
        score=_distance_to_score(match.distance),
        distance=match.distance,
        metadata=metadata,
    )


def _deduplicate(results: list[VectorSearchResult]) -> list[VectorSearchResult]:
    """Collapse multiple fragments of the same symbol (same symbol_id +
    chunk_type) to their single highest-scoring hit — `results` must
    already be sorted by score descending."""
    seen: set[tuple[str, str]] = set()
    deduped: list[VectorSearchResult] = []
    for result in results:
        key = (result.symbol_id or result.chunk_id, result.chunk_type.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def search(
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    settings: Settings,
    query: VectorSearchQuery,
) -> list[VectorSearchResult]:
    """Repository-scoped semantic search — see the indexing task's
    "Retrieval service" for the required behavior this implements
    end-to-end (empty-query/top_k validation, embedding, repository
    scoping, allow-listed filters, score conversion, sorting, minimum-
    score filtering, deduplication, exact source citations)."""
    if not query.query or not query.query.strip():
        raise InvalidQueryError("Query text must not be empty.")

    top_k = _validate_top_k(query.top_k, settings)
    where = _build_where(query)
    query_embedding = embedding_provider.embed_query(query.query)

    # Overfetch a little so qualified_name_prefix filtering and
    # near-duplicate dedup still leave up to `top_k` results.
    fetch_k = min(top_k * 3, settings.vector_max_top_k * 3)

    matches = vector_store.search(
        query.repository_id, query_embedding, top_k=fetch_k, where=where or None
    )
    results = [_to_result(match, repository_id=query.repository_id) for match in matches]

    if query.qualified_name_prefix:
        results = [
            r for r in results if (r.qualified_name or "").startswith(query.qualified_name_prefix)
        ]

    minimum_score = (
        query.minimum_score if query.minimum_score is not None else settings.vector_min_score
    )
    if minimum_score:
        results = [r for r in results if r.score >= minimum_score]

    results.sort(key=lambda r: r.score, reverse=True)
    results = _deduplicate(results)
    return results[:top_k]

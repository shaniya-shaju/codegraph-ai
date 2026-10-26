"""Vector-indexing and semantic-search endpoints.

Extends API_SPEC.md's repository contract — see the indexing task's "API
endpoints". No endpoint here calls an LLM (search is embedding-similarity
only) and none accepts an arbitrary raw ChromaDB filter (SECURITY.md).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.domain.repositories.store import get_repository
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import IndexingStatistics, VectorSearchQuery, VectorSearchResult
from app.indexing.chroma_store import get_vector_store
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.exceptions import IndexingError, InvalidFilterError, InvalidQueryError
from app.indexing.indexing_service import delete_repository_index
from app.indexing.metadata import get_manifest_for_repository
from app.indexing.retrieval_service import search as run_search
from app.indexing.sentence_transformer_provider import get_embedding_provider
from app.indexing.vector_store import VectorStore
from app.ingestion.analysis import analyze_and_index_repository

router = APIRouter(tags=["indexing"])


def _require_repository(repository_id: str, db: Session = Depends(get_db)) -> str:
    if get_repository(db, repository_id) is None:
        raise NotFoundError(f"No repository with id {repository_id} exists.")
    return repository_id


class IndexRequest(BaseModel):
    force_reindex: bool = False


class IndexResponse(BaseModel):
    repository_id: str
    file_count: int
    symbol_count: int
    chunk_count: int
    indexed_chunk_count: int
    skipped_chunk_count: int
    deleted_stale_chunk_count: int
    embedding_model: str
    embedding_dimension: int | None
    duration_ms: int
    error_count: int

    @classmethod
    def from_statistics(cls, stats: IndexingStatistics) -> "IndexResponse":
        return cls(
            repository_id=stats.repository_id,
            file_count=stats.file_count,
            symbol_count=stats.symbol_count,
            chunk_count=stats.chunk_count,
            indexed_chunk_count=stats.indexed_chunk_count,
            skipped_chunk_count=stats.skipped_chunk_count,
            deleted_stale_chunk_count=stats.deleted_stale_chunk_count,
            embedding_model=stats.embedding_model,
            embedding_dimension=stats.embedding_dimension,
            duration_ms=stats.duration_ms,
            error_count=stats.error_count,
        )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = None
    chunk_types: list[ChunkType] | None = None
    file_paths: list[str] | None = None
    minimum_score: float | None = None


class SearchResultItem(BaseModel):
    chunk_id: str
    symbol_id: str | None
    chunk_type: ChunkType
    qualified_name: str | None
    file_path: str
    start_line: int
    end_line: int
    score: float
    content: str


class SearchResponse(BaseModel):
    repository_id: str
    query: str
    results: list[SearchResultItem]

    @classmethod
    def from_results(
        cls, repository_id: str, query: str, results: list[VectorSearchResult]
    ) -> "SearchResponse":
        return cls(
            repository_id=repository_id,
            query=query,
            results=[
                SearchResultItem(
                    chunk_id=r.chunk_id,
                    symbol_id=r.symbol_id,
                    chunk_type=r.chunk_type,
                    qualified_name=r.qualified_name,
                    file_path=r.file_path,
                    start_line=r.start_line,
                    end_line=r.end_line,
                    score=r.score,
                    content=r.content,
                )
                for r in results
            ],
        )


class IndexStatisticsResponse(BaseModel):
    repository_id: str
    chunk_count: int
    embedding_models_in_use: list[str]


@router.post("/repositories/{repository_id}/index", response_model=IndexResponse, status_code=201)
def index_repository_endpoint(
    payload: IndexRequest,
    *,
    repository_id: str = Depends(_require_repository),
    db: Session = Depends(get_db),
) -> IndexResponse:
    try:
        stats = analyze_and_index_repository(
            db, repository_id=repository_id, force_reindex=payload.force_reindex
        )
    except IndexingError as exc:
        raise ValidationError(str(exc)) from exc
    return IndexResponse.from_statistics(stats)


@router.get(
    "/repositories/{repository_id}/index/statistics", response_model=IndexStatisticsResponse
)
def get_index_statistics(
    *,
    repository_id: str = Depends(_require_repository),
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> IndexStatisticsResponse:
    manifest = get_manifest_for_repository(db, repository_id)
    chunk_count = vector_store.count(repository_id)
    models_in_use = sorted({entry.embedding_model for entry in manifest})
    return IndexStatisticsResponse(
        repository_id=repository_id, chunk_count=chunk_count, embedding_models_in_use=models_in_use
    )


@router.post("/repositories/{repository_id}/search", response_model=SearchResponse)
def search_repository(
    payload: SearchRequest,
    *,
    repository_id: str = Depends(_require_repository),
    settings: Settings = Depends(get_settings),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    vector_store: VectorStore = Depends(get_vector_store),
) -> SearchResponse:
    query = VectorSearchQuery(
        repository_id=repository_id,
        query=payload.query,
        top_k=payload.top_k or settings.vector_default_top_k,
        chunk_types=payload.chunk_types,
        file_paths=payload.file_paths,
        minimum_score=payload.minimum_score,
    )
    try:
        results = run_search(embedding_provider, vector_store, settings, query)
    except (InvalidQueryError, InvalidFilterError) as exc:
        raise ValidationError(str(exc)) from exc

    return SearchResponse.from_results(repository_id, payload.query, results)


@router.delete("/repositories/{repository_id}/index", status_code=204)
def delete_repository_index_endpoint(
    *,
    repository_id: str = Depends(_require_repository),
    db: Session = Depends(get_db),
    vector_store: VectorStore = Depends(get_vector_store),
) -> None:
    delete_repository_index(db, vector_store, repository_id=repository_id)

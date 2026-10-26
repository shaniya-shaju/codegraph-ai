"""Wraps app.indexing.retrieval_service — never duplicates Chroma logic
(see "Vector retriever adapter": "Do not duplicate Chroma logic")."""

from typing import Protocol

from app.core.config import Settings
from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.rag.models import RetrievalEvidence
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import VectorSearchQuery, VectorSearchResult
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.retrieval_service import search as run_vector_search
from app.indexing.vector_store import VectorStore

_CHUNK_TYPE_TO_EVIDENCE_TYPE = {
    ChunkType.MODULE: EvidenceType.MODULE,
    ChunkType.API_ENDPOINT: EvidenceType.API_ENDPOINT,
}


class VectorSearchFn(Protocol):
    def __call__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        settings: Settings,
        query: VectorSearchQuery,
    ) -> list[VectorSearchResult]: ...


def _evidence_type_for(chunk_type: ChunkType) -> EvidenceType:
    return _CHUNK_TYPE_TO_EVIDENCE_TYPE.get(chunk_type, EvidenceType.CODE_CHUNK)


def _to_evidence(result: VectorSearchResult) -> RetrievalEvidence:
    return RetrievalEvidence(
        id=f"vector:{result.chunk_id}",
        repository_id=result.repository_id,
        evidence_type=_evidence_type_for(result.chunk_type),
        symbol_id=result.symbol_id,
        qualified_name=result.qualified_name,
        file_path=result.file_path,
        start_line=result.start_line,
        end_line=result.end_line,
        content=result.content,
        source=EvidenceSource.VECTOR,
        vector_score=result.score,
        graph_distance=None,
        exact_match_score=None,
        relationship_type=None,
        metadata={"chunk_id": result.chunk_id, "chunk_type": result.chunk_type.value},
    )


class VectorRetriever:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        settings: Settings,
        *,
        search_fn: VectorSearchFn = run_vector_search,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._settings = settings
        self._search_fn = search_fn

    def run(
        self,
        *,
        repository_id: str,
        query: str,
        top_k: int,
        chunk_types: list[ChunkType] | None = None,
        file_paths: list[str] | None = None,
        minimum_score: float | None = None,
    ) -> list[RetrievalEvidence]:
        vector_query = VectorSearchQuery(
            repository_id=repository_id,
            query=query,
            top_k=top_k,
            chunk_types=chunk_types,
            file_paths=file_paths,
            minimum_score=minimum_score,
        )
        results = self._search_fn(
            self._embedding_provider, self._vector_store, self._settings, vector_query
        )
        return [_to_evidence(r) for r in results]

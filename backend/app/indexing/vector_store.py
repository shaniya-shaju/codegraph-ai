"""Vector-store interface — kept separate from ChromaDB-specific code
(rule 10: "ChromaDB-specific code must be isolated from domain logic").
app.indexing.indexing_service and retrieval_service depend only on this
Protocol; chroma_store.py is the sole concrete implementation and the
only module that imports ``chromadb``.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.retrieval.models import CodeChunk


@dataclass(frozen=True)
class VectorStoreMatch:
    """One search hit, already translated out of Chroma's native shape —
    still store-agnostic (no `score` yet; that's a retrieval_service
    concern once it decides how to convert distance -> score)."""

    chunk_id: str
    content: str
    metadata: dict[str, object] = field(default_factory=dict)
    distance: float | None = None


class VectorStore(Protocol):
    def upsert(
        self,
        repository_id: str,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> None: ...

    def delete(self, repository_id: str, chunk_ids: list[str]) -> None: ...

    def delete_repository(self, repository_id: str) -> None: ...

    def search(
        self,
        repository_id: str,
        query_embedding: list[float],
        *,
        top_k: int,
        where: dict[str, object] | None = None,
    ) -> list[VectorStoreMatch]: ...

    def count(self, repository_id: str) -> int: ...

    def health_check(self) -> str: ...

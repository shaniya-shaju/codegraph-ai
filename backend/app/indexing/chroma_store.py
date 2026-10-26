"""The ChromaDB adapter.

The ONLY module in this codebase that imports ``chromadb`` (rule 10:
"ChromaDB-specific code must be isolated from domain logic") —
indexing_service.py and retrieval_service.py depend only on the
VectorStore Protocol. Never exposes a raw Chroma client/collection/query
result past this module (rule 13).

Collection design (see the indexing task's "ChromaDB collection design"):
**Option A, one collection per repository.** Chosen for strong isolation
and trivial repository deletion (drop the collection, not a filtered bulk
delete) — the same tradeoff DATA_MODEL.md already documents for this
store. Collection names are always sanitized + hashed (see
``sanitize_collection_name``); a raw repository_id or name is never used
directly as one, since Chroma restricts collection-name characters/length.
"""

import hashlib
import logging
import re
from functools import lru_cache

import chromadb
from chromadb.config import Settings as ChromaClientSettings

from app.core.config import Settings, get_settings
from app.domain.retrieval.models import CodeChunk
from app.indexing.exceptions import (
    InvalidFilterError,
    VectorStoreConnectionError,
    VectorStoreQueryError,
)
from app.indexing.vector_store import VectorStoreMatch

logger = logging.getLogger(__name__)

_COLLECTION_NAME_MAX_LENGTH = 63
_INVALID_NAME_CHARS = re.compile(r"[^a-z0-9_-]")

# Metadata filter keys the API/retrieval layer may request — never an
# arbitrary raw Chroma `where` clause (SECURITY.md: "Do not accept
# arbitrary raw ChromaDB where clauses through the API").
ALLOWED_FILTER_KEYS = frozenset({"chunk_type", "file_path", "symbol_id", "language"})


def sanitize_collection_name(repository_id: str, *, prefix: str) -> str:
    """Deterministic, Chroma-safe collection name for a repository.

    Never the raw repository_id/name: normalizes to `[a-z0-9_-]`, then
    appends a short content hash of the *original* repository_id so two
    different ids that happen to normalize the same way still can't
    collide.
    """
    digest = hashlib.sha256(repository_id.encode("utf-8")).hexdigest()[:10]
    prefix_clean = _INVALID_NAME_CHARS.sub("_", prefix.lower()).strip("_-") or "codegraph"
    normalized = _INVALID_NAME_CHARS.sub("_", repository_id.lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_-")

    reserved = len(prefix_clean) + len(digest) + 2  # two separating underscores
    max_body_len = _COLLECTION_NAME_MAX_LENGTH - reserved
    body = normalized[:max_body_len] if max_body_len > 0 else ""

    name = f"{prefix_clean}_{body}_{digest}" if body else f"{prefix_clean}_{digest}"
    if not name[0].isalnum():
        name = "c" + name
    if not name[-1].isalnum():
        name = name + "0"
    return name[:_COLLECTION_NAME_MAX_LENGTH]


class ChromaVectorStore:
    """Persistent, local ChromaDB adapter — see ARCHITECTURE.md
    "Deployment view" (embedded, not a separate service)."""

    def __init__(self, settings: Settings) -> None:
        self._collection_prefix = settings.chroma_collection_prefix
        try:
            self._client = chromadb.PersistentClient(
                path=settings.chroma_persist_directory,
                settings=ChromaClientSettings(anonymized_telemetry=False),
            )
        except Exception as exc:
            raise VectorStoreConnectionError(
                f"Failed to initialize ChromaDB: {exc.__class__.__name__}"
            ) from exc

    def health_check(self) -> str:
        try:
            self._client.heartbeat()
            return "ok"
        except Exception:
            return "unavailable"

    def upsert(
        self, repository_id: str, chunks: list[CodeChunk], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise VectorStoreQueryError(
                f"upsert() received {len(chunks)} chunks but {len(embeddings)} embeddings."
            )
        if not chunks:
            return

        collection = self._get_or_create_collection(repository_id)
        ids = [chunk.id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [self._to_chroma_metadata(chunk) for chunk in chunks]

        try:
            # chroma-core's stubs are stricter than the runtime API actually
            # requires for plain list[list[float]] embeddings / list[dict]
            # metadatas — both are accepted and documented usage.
            collection.upsert(
                ids=ids,
                embeddings=embeddings,  # type: ignore[arg-type]
                documents=documents,
                metadatas=metadatas,  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise VectorStoreQueryError(f"Chroma upsert failed: {exc.__class__.__name__}") from exc

    def delete(self, repository_id: str, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        collection = self._get_or_create_collection(repository_id)
        try:
            collection.delete(ids=chunk_ids)
        except Exception as exc:
            raise VectorStoreQueryError(f"Chroma delete failed: {exc.__class__.__name__}") from exc

    def delete_repository(self, repository_id: str) -> None:
        name = self._collection_name(repository_id)
        try:
            self._client.delete_collection(name)
        except Exception:
            logger.info("No Chroma collection to delete for this repository (already absent).")

    def search(
        self,
        repository_id: str,
        query_embedding: list[float],
        *,
        top_k: int,
        where: dict[str, object] | None = None,
    ) -> list[VectorStoreMatch]:
        collection = self._get_or_create_collection(repository_id)
        chroma_where = self._build_where(where)

        try:
            result = collection.query(
                query_embeddings=[query_embedding],  # type: ignore[arg-type]
                n_results=top_k,
                where=chroma_where or None,  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise VectorStoreQueryError(f"Chroma search failed: {exc.__class__.__name__}") from exc

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        matches: list[VectorStoreMatch] = []
        for index, chunk_id in enumerate(ids):
            matches.append(
                VectorStoreMatch(
                    chunk_id=chunk_id,
                    content=documents[index] if index < len(documents) else "",
                    metadata=dict(metadatas[index])
                    if index < len(metadatas) and metadatas[index]
                    else {},
                    distance=distances[index] if index < len(distances) else None,
                )
            )
        return matches

    def count(self, repository_id: str) -> int:
        collection = self._get_or_create_collection(repository_id)
        try:
            return int(collection.count())
        except Exception as exc:
            raise VectorStoreQueryError(f"Chroma count failed: {exc.__class__.__name__}") from exc

    def _collection_name(self, repository_id: str) -> str:
        return sanitize_collection_name(repository_id, prefix=self._collection_prefix)

    def _get_or_create_collection(self, repository_id: str) -> chromadb.Collection:
        name = self._collection_name(repository_id)
        try:
            # embedding_function=None + hnsw:space="cosine": every vector
            # written or queried here must be an explicit, already-computed
            # embedding — never Chroma's own implicit default embedding
            # function, which could silently differ between indexing and
            # retrieval (see the indexing task's "Do not rely on an
            # implicit Chroma embedding function").
            return self._client.get_or_create_collection(
                name=name,
                embedding_function=None,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise VectorStoreConnectionError(
                f"Failed to access the vector collection for this repository: "
                f"{exc.__class__.__name__}"
            ) from exc

    @staticmethod
    def _to_chroma_metadata(chunk: CodeChunk) -> dict[str, str | int | float | bool]:
        raw: dict[str, object] = {
            "repository_id": chunk.repository_id,
            "file_id": chunk.file_id,
            "symbol_id": chunk.symbol_id,
            "parent_symbol_id": chunk.parent_symbol_id,
            "chunk_type": chunk.chunk_type.value,
            "language": chunk.language,
            "qualified_name": chunk.qualified_name,
            "display_name": chunk.display_name,
            "file_path": chunk.file_path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content_hash": chunk.content_hash,
            "parser_version": chunk.parser_version,
            "embedding_model": chunk.embedding_model,
            "fragment_index": chunk.fragment_index,
            "fragment_count": chunk.fragment_count,
        }
        for key, value in chunk.metadata.items():
            if isinstance(value, str | int | float | bool):
                raw[f"extra_{key}"] = value
        # Chroma rejects None metadata values outright — omit the key
        # instead of storing a null.
        return {key: value for key, value in raw.items() if value is not None}  # type: ignore[misc]

    @staticmethod
    def _build_where(where: dict[str, object] | None) -> dict[str, object]:
        if not where:
            return {}
        invalid_keys = set(where) - ALLOWED_FILTER_KEYS
        if invalid_keys:
            raise InvalidFilterError(f"Unsupported filter key(s): {sorted(invalid_keys)}")

        clauses: list[dict[str, object]] = []
        for key, value in where.items():
            if isinstance(value, list):
                clauses.append({key: {"$in": value}})
            else:
                clauses.append({key: value})

        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}


@lru_cache
def get_vector_store() -> ChromaVectorStore:
    return ChromaVectorStore(get_settings())


def reset_vector_store() -> None:
    """Test-only: clear the cached store so the next ``get_vector_store()``
    builds a fresh client against current settings (e.g. a new temp dir)."""
    get_vector_store.cache_clear()

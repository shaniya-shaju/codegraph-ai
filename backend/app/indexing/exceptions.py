"""Indexing-layer-internal exception types.

Distinct from app.core.exceptions.AppError (HTTP-facing) — mirrors the
pattern in app.parsing.exceptions / app.graph.exceptions.
"""


class IndexingError(Exception):
    """Base class for indexing-layer-internal errors."""


class ChunkValidationError(IndexingError):
    """A built CodeChunk is missing required metadata or is malformed."""


class EmbeddingProviderError(IndexingError):
    """The embedding provider failed to load or to embed the given input."""


class VectorStoreError(IndexingError):
    """Base class for vector-store (ChromaDB) errors."""


class VectorStoreConnectionError(VectorStoreError):
    """The vector store could not be reached or initialized."""


class VectorStoreQueryError(VectorStoreError):
    """A vector-store operation (upsert/query/delete) failed."""


class InvalidFilterError(IndexingError):
    """A requested metadata filter is not on the allow-list."""


class InvalidQueryError(IndexingError):
    """The search query text or top_k is missing/out of bounds."""

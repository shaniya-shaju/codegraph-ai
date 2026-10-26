"""Enumerations for the vector-retrieval domain models."""

from enum import StrEnum


class ChunkType(StrEnum):
    """Primary syntax-aware chunk types (see app.indexing.chunker).

    ``OPTIONAL_CONTEXT`` is reserved for future supplementary chunks (e.g.
    a standalone module-overview block) — this stage's chunker does not
    emit it yet; see the indexing task's final report for why.
    """

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    API_ENDPOINT = "api_endpoint"
    OPTIONAL_CONTEXT = "optional_context"


class DistanceMetric(StrEnum):
    """The ChromaDB HNSW space every collection is created with.

    Cosine is used because embeddings are (by default) normalized before
    storage — see EMBEDDING_NORMALIZE and indexing/chroma_store.py.
    """

    COSINE = "cosine"

"""Typed vector-retrieval domain models.

See ARCHITECTURE.md "Vector-indexing strategy" and DATA_MODEL.md "ChromaDB:
vector store layout". These are what app.indexing's services accept and
return — never a raw ChromaDB query/collection result past
app.indexing.chroma_store (rule 13: "Retrieval results must not expose raw
internal ChromaDB objects").
"""

from dataclasses import dataclass, field

from app.domain.retrieval.enums import ChunkType


@dataclass(frozen=True)
class CodeChunk:
    """One syntax-aware, embeddable unit of source code.

    ``symbol_id`` is the parser-generated id (see
    app.domain.code_symbols.models) for MODULE/CLASS/FUNCTION/METHOD
    chunks; API_ENDPOINT chunks use their own deterministic id (see
    hashing.py) since an endpoint isn't itself a parsed symbol.
    ``parent_symbol_id`` is set only for fragments of an oversized symbol,
    pointing back at the symbol they were split from.
    """

    id: str
    repository_id: str
    file_id: str
    symbol_id: str | None
    parent_symbol_id: str | None
    chunk_type: ChunkType
    language: str
    qualified_name: str | None
    display_name: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    parser_version: str
    embedding_model: str | None
    fragment_index: int
    fragment_count: int
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexedDocument:
    chunk: CodeChunk
    vector_dimension: int
    indexed_at: str
    collection_name: str


@dataclass(frozen=True)
class VectorSearchQuery:
    repository_id: str
    query: str
    top_k: int
    chunk_types: list[ChunkType] | None = None
    file_paths: list[str] | None = None
    symbol_types: list[ChunkType] | None = None
    minimum_score: float | None = None
    # Not in the indexing task's literal field list, but required by its
    # own "Retrieval filtering" section ("Support safe filters for: ...
    # qualified-name prefix") — added to actually satisfy that behavior.
    qualified_name_prefix: str | None = None


@dataclass(frozen=True)
class VectorSearchResult:
    chunk_id: str
    repository_id: str
    symbol_id: str | None
    chunk_type: ChunkType
    qualified_name: str | None
    file_path: str
    start_line: int
    end_line: int
    content: str
    score: float
    distance: float | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexingStatistics:
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

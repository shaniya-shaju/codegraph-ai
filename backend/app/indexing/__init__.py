"""Syntax-aware code chunking, embeddings, and ChromaDB vector indexing.

See ARCHITECTURE.md "Vector-indexing strategy" and DATA_MODEL.md
"ChromaDB: vector store layout". Layering, strictly one-directional:

- ``chunker.py`` / ``text_builder.py`` / ``hashing.py`` — deterministic,
  syntax-aware chunk construction from app.parsing's ParsedFile output.
  Never regex-based fixed-size splitting as the primary strategy.
- ``embedding_provider.py`` (Protocol) + ``sentence_transformer_provider.py``
  — the only local, default implementation. No domain code depends on
  ``sentence_transformers`` directly.
- ``vector_store.py`` (Protocol) + ``chroma_store.py`` — the only module
  that imports ``chromadb``.
- ``metadata.py`` — the indexing manifest (what's currently indexed, with
  what content hash and embedding model), used to make reindexing skip
  unchanged chunks.
- ``indexing_service.py`` — write-side orchestration: chunk, embed what's
  new/changed, upsert, delete what's stale.
- ``retrieval_service.py`` — read-side orchestration: bounded,
  repository-scoped semantic search for the API layer.

Nothing here calls an LLM, builds a LangChain chain, or fuses graph and
vector results — see the indexing task's non-goals.
"""

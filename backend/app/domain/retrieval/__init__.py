"""API-independent vector-retrieval domain models.

See ARCHITECTURE.md "Vector-indexing strategy" and DATA_MODEL.md "ChromaDB:
vector store layout". Nothing here imports ``chromadb`` or
``sentence_transformers`` (rule 10: ChromaDB-specific code stays isolated
in app.indexing.chroma_store) — this package is the pure output/input
contract for app.indexing's services.
"""

"""API-independent hybrid-retrieval domain models.

See ARCHITECTURE.md and the hybrid-retrieval task's "Query analysis
models" / "Unified evidence model" / "Hybrid retrieval result". These are
what app.rag's services accept and return — never a raw LangChain
message/document object (rule: "graph access, vector search and
deterministic code facts must remain implemented through the existing
application services").
"""

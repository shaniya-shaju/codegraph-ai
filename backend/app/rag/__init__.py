"""Hybrid graph + vector retrieval — see ARCHITECTURE.md "Hybrid
retrieval orchestrator (LangChain)".

Given a natural-language question, this package classifies its intent,
resolves mentioned entities to actual repository symbols, plans and runs
vector/graph/symbol retrieval through the existing application services
(app.indexing, app.graph — never by parsing source or issuing raw
Cypher itself), fuses and ranks the resulting evidence, and returns a
structured ``HybridRetrievalResult``.

Does not generate a final natural-language answer — see
app.rag.hybrid_retriever's module docstring.
"""

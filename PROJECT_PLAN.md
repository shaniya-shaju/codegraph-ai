# Project Plan

## Goal

Build **CodeGraph AI**, a system that lets an engineer point at a Python
repository and:

1. Ask natural-language questions about the codebase and get answers
   grounded in the actual code, with file/line citations.
2. Ask "what breaks if I change X?" and get a deterministic, graph-derived
   change-impact set, summarized in natural language.

The project must demonstrate that combining a **deterministic knowledge
graph** with **vector retrieval** and an **LLM** produces materially more
trustworthy answers than an LLM-only or vector-only RAG system, because
structural facts (calls, imports, inheritance, dependencies) come from
static analysis, not from model inference.

## MVP scope

In scope for v1:

- Ingestion of a single Python repository at a time, from a local path or a
  public Git URL.
- Tree-sitter-based parsing of `.py` files into deterministic graph entities
  (see [DATA_MODEL.md](DATA_MODEL.md) for the full node/relationship list).
- A Neo4j knowledge graph, isolated per `repository_id`.
- Chunking and embedding of code into ChromaDB, isolated per `repository_id`.
- A LangChain-orchestrated hybrid retrieval flow with two independent
  retrievers: a graph retriever (Cypher) and a vector retriever (ChromaDB
  similarity search).
- A Q&A endpoint that answers questions about the ingested repository with
  file path + line-number citations.
- A change-impact-analysis endpoint: given a function/class/method (or a
  file + line range), deterministically compute the transitive set of
  dependents via graph traversal, then have the LLM summarize it in
  natural language.
- A React + Cytoscape.js UI for: triggering ingestion, chatting with the
  repository, browsing/exploring the code graph, and viewing impact
  analysis results.
- SQLite for application/operational metadata (repository records,
  ingestion run history), with a schema written so a later move to
  PostgreSQL is a connection-string and dialect change, not a rewrite.
- Docker Compose for local orchestration of Neo4j, the backend, and the
  frontend.

## Non-goals (explicitly out of scope for v1)

- **Multi-language support.** Only Python is parsed. Files in other
  languages may be recorded as `File` nodes for graph completeness but are
  not deeply parsed into Module/Class/Function entities.
- **Security or vulnerability analysis** of the ingested repository's code
  (no SAST, no secret scanning, no dependency-CVE checks).
- **Authentication/authorization** of CodeGraph AI's own users. This is a
  single-tenant, local/dev tool for the MVP. `repository_id` isolation is a
  data-partitioning mechanism, not a multi-tenant security boundary — see
  [SECURITY.md](SECURITY.md).
- **Multi-repository cross-referencing.** Each repository's graph and
  vector index are isolated; the MVP does not answer questions that span
  two repositories.
- **Real-time file watching / incremental live sync.** Re-indexing is
  triggered explicitly (a "reindex" action), not on every file save.
- **Code modification.** The system never writes back to the ingested
  repository; it is read-only analysis.
- **Microservice decomposition, message queues, or a plugin architecture.**
  One backend process, three data stores.
- **MongoDB**, or any document database, anywhere in the stack.

## Milestones

| Milestone | Deliverable |
|---|---|
| M0 — Planning | This documentation set: architecture, data model, API spec, evaluation plan, security boundaries (current milestone). |
| M1 — Ingestion & graph | Repo cloning/reading, Tree-sitter parsing, deterministic graph construction into Neo4j, scoped by `repository_id`. Pytest suite over fixture repos. |
| M2 — Vector indexing | Chunking strategy implemented, embeddings written to ChromaDB per repository, re-index/delta logic. |
| M3 — Hybrid retrieval & Q&A | GraphRetriever, VectorRetriever, LangChain orchestration, citation-checked Q&A endpoint. |
| M4 — Change-impact analysis | Graph-traversal impact service, impact API endpoint, LLM summarization layer. |
| M5 — Frontend | Repository management UI, chat UI with citations, Cytoscape.js graph explorer, impact-analysis view. |
| M6 — Evaluation & hardening | Execution of the evaluation plan, fixture-based accuracy numbers, write-up of results. |

Milestones are sequential dependencies (M2 needs M1's graph and parsed
files; M3 needs M1 and M2; M4 needs M1). Frontend work in M5 can start
incrementally once the corresponding API endpoints from M1–M4 exist.

## Success criteria

- A Q&A answer about a fixture repository cites the correct file and line
  range for at least the primary fact being asked about, verified against a
  hand-labeled test set (see [EVALUATION_PLAN.md](EVALUATION_PLAN.md)).
- A change-impact query for a function with a known call graph in a
  fixture repository returns the correct transitive dependent set (measured
  by precision/recall against a hand-labeled ground truth).
- No citation in any generated answer references a file/line that was not
  actually part of the retrieved context (zero-hallucinated-citation
  target on the evaluation set).
- Ingesting a repository of a few thousand lines of Python completes and
  produces a browsable graph without manual intervention.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tree-sitter's static `CALLS` resolution can't always resolve dynamic dispatch (duck typing, `getattr`, decorators that rewrite behavior) | Document this as a known limitation; resolve by best-effort name/scope matching; do not claim 100% call-graph accuracy. |
| LLM ignores retrieved context and answers from parametric memory | Enforce a citation-validation step that rejects/regenerates answers whose citations don't match retrieved chunks. |
| Large repositories make full-graph ingestion slow | Scope MVP evaluation to small/medium repositories; note performance limits rather than pre-optimizing. |
| Embedding model choice affects retrieval quality unpredictably | Keep the embedding provider pluggable behind a LangChain interface so it can be swapped without touching retrieval logic. |
| Scope creep toward auth/multi-language/security features | This document and [AGENTS.md](AGENTS.md) explicitly list them as non-goals; any request to add them should be redirected to a future-work note instead. |

## Future work (explicitly deferred, not part of this plan)

- Authentication and multi-tenant isolation.
- Multi-language parsing (JavaScript/TypeScript, Java, Go, ...).
- Security/vulnerability scanning of ingested code.
- Incremental/live re-indexing on file change.
- Cross-repository graph queries.

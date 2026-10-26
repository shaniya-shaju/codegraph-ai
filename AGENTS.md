# AGENTS.md — Rules for anyone (human or AI) working in this repository

This file is the operating contract for this codebase. It applies equally to
human contributors and AI coding agents (Claude Code or otherwise). If a
suggestion conflicts with this file, this file wins. If this file conflicts
with [ARCHITECTURE.md](ARCHITECTURE.md), [DATA_MODEL.md](DATA_MODEL.md), or
[API_SPEC.md](API_SPEC.md), stop and flag the conflict instead of guessing.

## The ten non-negotiable rules

1. **Tree-sitter and deterministic logic generate the code graph.** Graph
   nodes and relationships come only from parsing and static analysis code
   that runs without an LLM in the loop.
2. **The LLM is never the source of truth for code relationships.** It may
   summarize, explain, or rank what the graph and vector store return. It
   may not invent a `CALLS`, `IMPORTS`, `EXTENDS`, etc. edge that the graph
   does not contain.
3. **LangChain orchestrates retrieval and generation — it does not parse
   source code.** Parsing lives in the Tree-sitter/ingestion layer only.
4. **Repository data is isolated by `repository_id`.** Every graph node,
   every vector-store entry, and every SQL row that is repository-scoped
   must carry `repository_id`, and every query must filter by it. See
   [DATA_MODEL.md](DATA_MODEL.md).
5. **Every generated answer includes file path and line-number citations**
   when the underlying fact has a source location. An answer that cites
   nothing it retrieved should be treated as a bug, not a style issue.
6. **Vector retrieval and graph retrieval are separate components.** Do not
   merge them into a single retriever class. They can be composed by an
   orchestrator, but each must be independently testable and independently
   callable.
7. **Python only for the MVP.** Do not add parsers, grammars, or
   language-detection logic for other languages.
8. **Do not implement:** security/vulnerability analysis of target
   repositories, multi-language parsing, or authentication/authorization.
   These are explicit non-goals for this phase — see
   [PROJECT_PLAN.md](PROJECT_PLAN.md) and [SECURITY.md](SECURITY.md).
9. **Avoid unnecessary abstractions and premature microservices.** One
   FastAPI backend, one frontend, three data stores. Don't introduce a
   message queue, a second backend service, or a plugin system unless a
   concrete requirement forces it.
10. **No MongoDB.** Application metadata is SQLite (MVP), migrating to
    PostgreSQL. The graph is Neo4j. The vector index is ChromaDB. No fourth
    database.

## What "done" looks like for a change

- Deterministic parsing logic has unit tests with fixture Python files and
  asserted node/edge counts (see [EVALUATION_PLAN.md](EVALUATION_PLAN.md)).
- Any new Cypher query filters by `repository_id`.
- Any new retrieval path that reaches the LLM produces citations, and there
  is a test asserting citations are present and reference retrieved
  context (not hallucinated paths/lines).
- Ruff, mypy, ESLint, and Prettier are clean (see
  [CONTRIBUTING.md](CONTRIBUTING.md)).
- Pytest and/or Vitest cover the change.
- Documentation in this set of files is updated in the same change if the
  behavior it describes changed — these docs are meant to stay accurate,
  not aspirational.

## Directory layout

The monorepo skeleton exists (see PROJECT_PLAN.md M1 for what's implemented
inside it so far — currently only the health endpoint and core scaffolding):

```
codegraph-ai/
  backend/
    app/
      api/routes/   # FastAPI routers — thin, no business logic (health.py so far)
      core/         # config, logging, exceptions — implemented
      domain/       # shared domain models (repository, graph entity, citation types) — placeholder
      ingestion/    # repo cloning/walking + orchestration of the ingestion pipeline — placeholder
      parsing/      # Tree-sitter based deterministic extraction — placeholder
      graph/        # Neo4j driver access, Cypher queries, GraphRetriever — placeholder
      indexing/     # ChromaDB client, chunking, embedding, VectorRetriever — placeholder
      rag/          # LangChain hybrid retrieval orchestration + Q&A generation — placeholder
      impact/       # change-impact traversal service — placeholder
      persistence/  # SQLAlchemy models, session, Alembic migrations — placeholder
      main.py
    tests/
      unit/
      integration/
      fixtures/
    pyproject.toml
    Dockerfile
  frontend/
    src/
      components/   # AppShell, HealthIndicator
      pages/         # Dashboard, Repository, Chat, Graph (placeholders beyond Dashboard)
      lib/           # API client, TanStack Query client
  evaluation/
    datasets/
    metrics/
    reports/
  scripts/
  sample-repositories/
  docker-compose.yml
```

"Placeholder" packages contain only a docstring-only `__init__.py` — no
logic — until the milestone that implements them (see PROJECT_PLAN.md).

## Guidance for AI agents specifically

- Prefer extending an existing module in `graph/`, `indexing/`, or `rag/`
  over creating a new top-level package.
- When asked to add a new node or relationship type to the graph, update
  [DATA_MODEL.md](DATA_MODEL.md) in the same change — the schema doc is the
  contract, not a description written after the fact.
- When asked to add an API endpoint, update [API_SPEC.md](API_SPEC.md) in
  the same change.
- Never write code that executes, `eval`s, or imports code from an ingested
  target repository. Parsing must stay static/AST-only (see
  [SECURITY.md](SECURITY.md)).
- If a request would violate one of the ten rules above, say so explicitly
  and propose the compliant alternative rather than silently complying.

# Architecture

## Overview

CodeGraph AI is a single FastAPI backend, a single React frontend, and three
data stores. There is no microservice split and no message queue — see
[AGENTS.md](AGENTS.md) rule 9.

```
                              ┌─────────────────────────┐
                              │        Frontend          │
                              │  React + TS + Vite +     │
                              │  Tailwind + Cytoscape.js │
                              └───────────┬──────────────┘
                                          │ HTTP (REST)
                              ┌───────────▼──────────────┐
                              │       FastAPI backend     │
                              │                            │
                              │  ┌──────────────────────┐  │
                              │  │  Ingestion pipeline   │  │
                              │  │  (Tree-sitter based)  │  │
                              │  └──────────┬───────────┘  │
                              │             │               │
                              │   ┌─────────▼─────────┐    │
                              │   │  Graph writer      │    │
                              │   │  Chunk/embed writer │    │
                              │   └───────┬────┬───────┘    │
                              │           │    │             │
                              │  ┌────────▼┐  ┌▼──────────┐  │
                              │  │ Graph    │  │ Vector    │  │
                              │  │ Retriever│  │ Retriever │  │
                              │  └────┬─────┘  └────┬──────┘  │
                              │       │             │          │
                              │       └──────┬──────┘          │
                              │        LangChain hybrid         │
                              │        retrieval orchestrator   │
                              │              │                   │
                              │        ┌─────▼─────┐            │
                              │        │    LLM     │            │
                              │        └───────────┘            │
                              │                                  │
                              │  ┌────────────────────────────┐  │
                              │  │ Change-impact-analysis      │  │
                              │  │ service (graph traversal)    │  │
                              │  └────────────────────────────┘  │
                              └──┬──────────┬──────────────┬────┘
                                 │          │              │
                          ┌──────▼───┐ ┌────▼─────┐  ┌─────▼─────┐
                          │  Neo4j    │ │ ChromaDB │  │  SQLite    │
                          │ (graph)   │ │ (vectors)│  │ (metadata) │
                          └───────────┘ └──────────┘  └────────────┘
```

## Components

### Ingestion pipeline

Owns the entire path from "a repository reference" to "a populated graph and
vector index." Responsible for cloning/reading source, walking the file
tree, invoking Tree-sitter, running deterministic extraction logic, and
handing results to the graph writer and the chunk/embed writer. This is the
**only** place static analysis happens (rule 1/3).

### Graph writer

Takes the deterministic entities and relationships produced by parsing and
writes them to Neo4j as nodes/edges, tagging every repository-scoped node
with `repository_id`. Pure translation layer — no inference, no LLM calls.

### Chunk/embed writer

Splits parsed code into retrieval-sized chunks (function/method/class
granularity, using Tree-sitter node boundaries rather than fixed line
counts) and writes embeddings to ChromaDB, tagged with `repository_id` and
source-location metadata.

### GraphRetriever

A component whose only job is: given a query (a symbol name, a structural
question), run Cypher against Neo4j scoped to a `repository_id` and return
graph facts with their source locations. No embeddings, no LLM calls inside
this component.

### VectorRetriever

A component whose only job is: given a query string, embed it and run a
similarity search against the `repository_id`-scoped ChromaDB collection,
returning chunks with their source-location metadata. No graph traversal
inside this component.

GraphRetriever and VectorRetriever are kept as separate, independently
testable components per rule 6 — neither is allowed to call the other
internally. Composition happens one layer up.

### Hybrid retrieval orchestrator (LangChain)

A LangChain chain that:

1. Classifies the incoming question (structural — "who calls X", "what
   depends on Y" — vs. semantic — "how does X work", "where is Y
   implemented" — vs. both).
2. Invokes GraphRetriever and/or VectorRetriever accordingly.
3. Merges results into a single context object, each item tagged with its
   file path and line range.
4. Prompts the LLM to answer using only that context, with an explicit
   instruction to cite `file:line` for every claim.
5. Validates the LLM's citations against the retrieved context set; if a
   citation doesn't match anything retrieved, the answer is rejected and
   regenerated (or returned with a warning) rather than shown as-is.

LangChain orchestrates this flow but never parses source code itself (rule
3) — by the time LangChain sees anything, parsing has already happened in
the ingestion pipeline.

### Change-impact-analysis service

Deterministic graph-traversal service, independent of the LLM:

1. Resolve the input (symbol name, or file + line) to a graph node via
   exact/qualified-name lookup.
2. Traverse relevant relationships (`CALLS`, `REFERENCES`, `EXTENDS`,
   `IMPORTS`, `DEPENDS_ON`, `HANDLED_BY`) in the reverse direction —
   "who points at this node" — up to a bounded depth, to build the
   transitive dependent set ("blast radius").
3. Return the impacted set as structured data (node type, qualified name,
   file path, line range) — this is the authoritative result.
4. Optionally, the LLM is given the impacted set (plus related chunks from
   VectorRetriever for context) and asked to produce a natural-language
   summary. The LLM may explain the impacted set; it may not add or remove
   nodes from it.

### Data stores

- **Neo4j** — the code knowledge graph. Source of truth for structural
  relationships. See [DATA_MODEL.md](DATA_MODEL.md).
- **ChromaDB** — one collection per `repository_id`, holding embedded code
  chunks with source-location metadata. See [DATA_MODEL.md](DATA_MODEL.md).
- **SQLite → PostgreSQL** — application/operational metadata: repository
  records, ingestion run history/status. Not the code graph, not vectors.

## Repository ingestion flow

1. Client calls `POST /api/v1/repositories` with a local path or Git URL.
2. Backend creates a `Repository` row in SQLite with a generated
   `repository_id` and status `pending`, and returns it immediately.
3. Ingestion runs (synchronously for MVP scale, or as a background task):
   a. Clone or copy the repository into an isolated per-`repository_id`
      workspace directory.
   b. Walk the directory tree, excluding common non-source directories
      (`.git`, `venv`, `.venv`, `node_modules`, `__pycache__`, etc.),
      recording `Directory` and `File` nodes as it goes.
   c. For each `.py` file, run the Tree-sitter parsing flow (below).
   d. Batch-write all resulting nodes/relationships to Neo4j.
   e. Chunk each parsed file and write embeddings to ChromaDB.
   f. Update the `Repository` row's status to `ready` (or `failed`, with an
      error message) and record stats on an `ingestion_runs` row.
4. Parse errors on individual files are logged and skipped; they do not
   fail the whole ingestion run — the graph is allowed to be partial with a
   recorded error, rather than all-or-nothing.

## Tree-sitter parsing flow

1. Parse the file with the Tree-sitter Python grammar to get a concrete
   syntax tree.
2. A deterministic visitor walks the tree and extracts, per rule 1 (no LLM
   involved at any point in this step):
   - Module-level identity (derived from the file's path relative to the
     repository root / nearest package).
   - `class` definitions → `Class` nodes; base classes → `EXTENDS` edges.
   - `def`/`async def` at module or class level → `Function`/`Method`
     nodes, with `start_line`/`end_line` captured directly from the syntax
     tree.
   - Function/method parameters → `Parameter` nodes and `HAS_PARAMETER`
     edges, including default values and type annotations where present.
   - `import`/`from ... import` statements → `IMPORTS` edges; targets that
     resolve outside the repository become `ExternalDependency` nodes and
     `DEPENDS_ON` edges.
   - Call expressions → `CALLS` edges, resolved by best-effort
     name/scope matching (not full dynamic dispatch resolution — see
     [PROJECT_PLAN.md](PROJECT_PLAN.md) risks).
   - Other name usages (a reference to a class/function/module without
     calling it) → `REFERENCES` edges.
   - Decorators matching common web-framework routing patterns (e.g.
     `@app.get`, `@router.post`) → `APIEndpoint` nodes and `HANDLED_BY`
     edges to the decorated function.
3. Every extracted entity carries the source location (`file path`,
   `start_line`, `end_line`) needed for citations later in the pipeline —
   this is where rule 5 (citations) originates.
4. Per-file parse failures are caught, logged with the file path and error,
   and do not abort the rest of the ingestion run.

## Vector-indexing strategy

- **Chunk granularity**: primarily one chunk per function/method/class body
  (using the same Tree-sitter node boundaries as graph extraction, not
  naive fixed-size line windows), plus a module-level chunk for module
  docstrings/headers.
- **Metadata per chunk**: `repository_id`, `file_path`, `start_line`,
  `end_line`, `qualified_name`, `node_type`.
- **Isolation**: one ChromaDB collection per `repository_id` (rather than a
  single collection filtered by metadata), so that deleting a repository's
  data is a collection drop, not a filtered delete.
- **Embedding provider**: pluggable behind a LangChain embeddings interface,
  selected via configuration (see [.env.example](.env.example)) — the
  retrieval and orchestration code does not hardcode a provider.
- **Re-indexing**: on re-ingestion, a per-file content hash determines
  whether a file's chunks need to be recomputed, avoiding redundant
  embedding calls for unchanged files.

## Change-impact-analysis design

See "Change-impact-analysis service" above for the component description.
Design principles:

- The impacted set is always computed by graph traversal first; the LLM is
  layered on top for explanation only (rule 2).
- Traversal depth is bounded and configurable (default: 3 hops) to keep
  results interpretable and to avoid the entire graph becoming "impacted"
  in a densely connected repository.
- The response distinguishes direct dependents (1 hop) from transitive
  dependents (2+ hops) so the summary can be prioritized.
- `APIEndpoint` nodes reached during traversal are surfaced distinctly,
  since a change reaching a public API endpoint is typically higher-impact
  than one that stays internal to a module.

## Reliability, readiness, and demo tooling

Added to make the backend observable, fail fast, and demo-ready:

- **Liveness vs. readiness**: `GET /api/v1/health/live` never touches a
  dependency (always instant); `GET /api/v1/health/ready` reports every
  dependency's state (database/Neo4j/Chroma/embedding provider) via one
  centralized `app.core.dependencies.status_service` — no endpoint
  performs its own ad hoc health check.
- **Neo4j fail-fast**: `app.graph.neo4j_client.Neo4jClient` bounds the
  driver's own transaction-retry loop (`max_transaction_retry_time`) and
  wraps every call in a generic, reusable `CircuitBreaker`
  (`app.core.dependencies.circuit_breaker`) — after repeated connectivity
  failures, further calls fail in microseconds with no I/O attempted at
  all, until a cooldown elapses and one probe call is allowed through.
  This is what fixes the ~30-55s wait a Neo4j outage previously caused on
  every graph-dependent request.
- **Repository analysis state**: `app.persistence.models.RepositoryAnalysisState`
  is the persisted, explicit per-subsystem (parser/graph/vector) status
  for a repository, owned exclusively by `app.ingestion.orchestrator` (the
  single place stage transitions and the derived `overall_status` are
  computed — see `app.ingestion.analysis_state_service.derive_overall_status`).
  Exposed via `GET /repositories/{id}/analysis`, triggered via
  `POST /repositories/{id}/analyze`, and streamed live via SSE at
  `GET /repositories/{id}/analysis/stream` (persisted state remains the
  source of truth; a reconnecting client can always fall back to the
  plain GET).
- **Graceful degradation**: hybrid retrieval already isolates a graph
  failure to a warning (vector evidence alone can still answer a
  question); that warning is now also translated into a plain-language
  `limitations` entry on the final grounded answer. Change-impact analysis
  has no vector-only fallback — it fails clearly with `503
  GRAPH_UNAVAILABLE` rather than guessing.
- **Standardized error contract**: every `AppError` response is
  `{"error": {"code", "message", "retryable", "details"}}`, with a
  `request_id` alongside it (see `app.core.request_context`) that's also
  returned as an `X-Request-ID` header and stamped onto every structured
  log line for that request.

## Deployment view

Docker Compose brings up: the FastAPI backend, Neo4j, and (once the
frontend exists) the Vite dev server / static build. ChromaDB runs as an
embedded/persistent client backed by a Docker volume rather than a separate
server process for the MVP, keeping the number of moving parts down (rule
9); this can change to a standalone ChromaDB service later without
affecting the retrieval interfaces, since VectorRetriever only depends on
the ChromaDB client API. SQLite is a file on a mounted volume; moving to
PostgreSQL later means adding a `postgres` service and changing the
connection string, not changing application code, provided the schema
follows the conventions in [DATA_MODEL.md](DATA_MODEL.md).

## Why these technology choices

- **Tree-sitter over the `ast` module**: incremental, error-tolerant
  parsing and a grammar that can extend to other languages later without
  changing the extraction architecture — even though only Python is in
  scope for v1.
- **Neo4j over a relational store for the graph**: relationships (`CALLS`,
  `IMPORTS`, transitive impact traversal) are graph-native queries; modeling
  transitive "who depends on this" in SQL would mean recursive CTEs
  fighting the grain of the data.
- **ChromaDB over a hosted vector service**: runs embedded/local, no extra
  infrastructure dependency, sufficient for MVP scale.
- **SQLite over PostgreSQL initially**: zero-setup for a final-year-project
  development loop; the schema is kept PostgreSQL-compatible (see
  [DATA_MODEL.md](DATA_MODEL.md)) so the migration is mechanical.
- **LangChain**: gives composable retriever/chain abstractions for the
  hybrid retrieval orchestration without writing a bespoke agent loop, while
  keeping parsing (rule 3) entirely outside of it.

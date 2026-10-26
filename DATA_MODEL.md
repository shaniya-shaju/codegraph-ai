# Data Model

CodeGraph AI has three data stores, each with a distinct responsibility.
None of them overlap in purpose:

- **Neo4j** — the code knowledge graph (structural ground truth).
- **ChromaDB** — embedded code chunks for semantic retrieval.
- **SQLite (→ PostgreSQL)** — operational/application metadata.

Every repository-scoped record in every store carries a `repository_id`
(a UUID string), and every read query must filter by it (see
[AGENTS.md](AGENTS.md) rule 4, [SECURITY.md](SECURITY.md)).

## Neo4j: knowledge graph schema

### Node types

| Node | Key properties |
|---|---|
| `Repository` | `repository_id` (unique), `name`, `source_type` (`local_path` \| `git_url`), `source_location`, `default_branch`, `created_at`, `last_indexed_at` |
| `Directory` | `repository_id`, `path` (relative to repo root), `name` |
| `File` | `repository_id`, `path`, `language`, `size_bytes`, `content_hash`, `loc` |
| `Module` | `repository_id`, `qualified_name`, `file_path` |
| `Class` | `repository_id`, `qualified_name`, `name`, `file_path`, `start_line`, `end_line`, `docstring` |
| `Function` | `repository_id`, `qualified_name`, `name`, `file_path`, `start_line`, `end_line`, `is_async`, `docstring` |
| `Method` | `repository_id`, `qualified_name`, `name`, `owner_class_qualified_name`, `file_path`, `start_line`, `end_line`, `is_async`, `docstring` |
| `Parameter` | `repository_id`, `name`, `index`, `default_value`, `annotation`, `owner_qualified_name` |
| `ExternalDependency` | `repository_id`, `name`, `version_spec`, `ecosystem` (e.g. `pypi`) |
| `APIEndpoint` | `repository_id`, `http_method`, `route_path`, `framework_hint`, `decorator_expression`, `file_path`, `start_line` (no `name`/`qualified_name` — the handler is reached via the `HANDLED_BY` edge, not a property on this node; symbol search matches it on `route_path` instead) |

`qualified_name` uses a dotted path derived from the package/module
structure, e.g. `app.services.billing.InvoiceService.charge`. For files
that aren't part of a formal package (no `__init__.py` chain), the
qualified name falls back to a path-derived pseudo-module name, e.g.
`scripts.migrate_users`.

Every node except `Repository` itself carries `repository_id` so that a
single Neo4j instance can safely hold multiple ingested repositories without
their graphs merging.

### Relationship types

| Relationship | Direction (from → to) | Meaning |
|---|---|---|
| `CONTAINS` | `Repository`/`Directory` → `Directory`/`File` | Filesystem containment |
| `DEFINES` | `File`/`Module` → `Class`/`Function`; `Class` → `Method` | "This file/class defines this entity" |
| `IMPORTS` | `Module`/`File` → `Module`/`ExternalDependency` | Import statement |
| `CALLS` | `Function`/`Method` → `Function`/`Method` | Best-effort statically resolved call |
| `HAS_PARAMETER` | `Function`/`Method` → `Parameter` | Signature membership |
| `EXTENDS` | `Class` → `Class` | Base-class relationship |
| `REFERENCES` | `Function`/`Method`/`Module` → `Class`/`Function`/`Module` | Name usage without a call |
| `HANDLED_BY` | `APIEndpoint` → `Function`/`Method` | Route-to-handler mapping |
| `DEPENDS_ON` | `File`/`Module` → `ExternalDependency` | Resolved third-party dependency |

### Example subgraph

```
(Repository {repository_id: "r1", name: "billing-service"})
  -[:CONTAINS]-> (Directory {path: "app/services"})
    -[:CONTAINS]-> (File {path: "app/services/billing.py"})
      -[:DEFINES]-> (Class {qualified_name: "app.services.billing.InvoiceService"})
        -[:DEFINES]-> (Method {qualified_name: "...InvoiceService.charge", start_line: 42, end_line: 58})
          -[:HAS_PARAMETER]-> (Parameter {name: "amount_cents"})
          -[:CALLS]-> (Method {qualified_name: "...PaymentGateway.submit"})
          -[:REFERENCES]-> (Class {qualified_name: "app.models.Invoice"})
      -[:IMPORTS]-> (ExternalDependency {name: "stripe", ecosystem: "pypi"})
(APIEndpoint {http_method: "POST", path: "/invoices/{id}/charge"})
  -[:HANDLED_BY]-> (Method {qualified_name: "...InvoiceService.charge"})
```

### Isolation rule

Every Cypher query issued by the application **must** include a
`repository_id` filter on the anchor node(s) of the query — there is no
query pattern in this system that legitimately spans two repositories in
v1 (see [PROJECT_PLAN.md](PROJECT_PLAN.md) non-goals). `ExternalDependency`
nodes are also scoped by `repository_id` (not deduplicated globally across
repositories) to keep isolation strict and deletion simple; cross-repository
dependency deduplication is future work, not a v1 concern.

## ChromaDB: vector store layout

- **One collection per repository**, named `repo_{repository_id}`. Dropping
  a repository means dropping its collection — no filtered bulk-delete
  needed.
- **Document**: the raw source text of the chunk (function/method/class
  body, or module header/docstring).
- **Metadata per chunk**:

  | Field | Description |
  |---|---|
  | `repository_id` | Owning repository |
  | `file_path` | Path relative to repo root |
  | `start_line` / `end_line` | Source location, for citations |
  | `qualified_name` | Same qualified-name scheme as the graph, so a chunk can be joined back to its graph node |
  | `node_type` | `module` \| `class` \| `function` \| `method` |
  | `content_hash` | Hash of the chunked source text, used to skip re-embedding unchanged chunks on reindex |

- **Embedding function**: configurable/pluggable (see
  [.env.example](.env.example)); not hardcoded into retrieval code.

Because `qualified_name` and `file_path`/`start_line`/`end_line` are shared
between the graph and the vector store, a hybrid answer can cite a location
regardless of whether the fact came from GraphRetriever or VectorRetriever.

## SQLite (→ PostgreSQL): application metadata

This store holds **operational** metadata only — never code structure and
never embeddings. Schema is written using SQLAlchemy models with
Alembic-style migrations in mind, and avoids SQLite-only types, so switching
the connection string to PostgreSQL is the only change needed later.

### `repositories`

| Column | Type | Notes |
|---|---|---|
| `repository_id` | text (UUID), PK | Same ID used to scope Neo4j nodes and the Chroma collection name |
| `name` | text | Display name |
| `source_type` | text | `local_path` \| `git_url` |
| `source_location` | text | Path or URL |
| `default_branch` | text, nullable | |
| `status` | text | `pending` \| `cloning` \| `parsing` \| `embedding` \| `ready` \| `failed` |
| `file_count` | integer, nullable | Populated after ingestion |
| `error_message` | text, nullable | Populated if `status = failed` |
| `created_at` | timestamp | |
| `last_indexed_at` | timestamp, nullable | |

### `ingestion_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | integer, PK | |
| `repository_id` | text, FK → `repositories.repository_id` | |
| `started_at` | timestamp | |
| `finished_at` | timestamp, nullable | |
| `status` | text | `running` \| `succeeded` \| `failed` |
| `files_parsed` | integer | |
| `parse_errors` | integer | Count of files skipped due to parse failure |
| `nodes_created` | integer | |
| `edges_created` | integer | |
| `chunks_embedded` | integer | |
| `error_log` | text, nullable | |

### `query_log` (minimal, for evaluation/telemetry)

| Column | Type | Notes |
|---|---|---|
| `id` | integer, PK | |
| `repository_id` | text, FK | |
| `question` | text | |
| `retrieval_mode` | text | `graph` \| `vector` \| `hybrid` |
| `created_at` | timestamp | |

No user/auth tables exist in v1 — see [SECURITY.md](SECURITY.md) for why.

## Cross-store identifier conventions

- `repository_id`: a UUIDv4 string, generated when a repository is
  registered. Used verbatim as: the Neo4j node property, the ChromaDB
  collection name suffix, and the SQLite primary/foreign key.
- `qualified_name`: dotted-path identifier, consistent between Neo4j nodes
  and ChromaDB chunk metadata, so a citation or a graph-to-vector join never
  needs a separate lookup table.
- Source location (`file_path`, `start_line`, `end_line`): stored
  redundantly in both Neo4j and ChromaDB (rather than normalized into one
  store) because both retrievers must be able to produce citations
  independently, per [AGENTS.md](AGENTS.md) rule 6.

# API Specification

This document defines the planned REST contract. No handlers exist yet —
this is the contract implementation must follow.

> **Note (Prompt 11):** this document was written before implementation
> began and several sections below (health, analysis/reindex, query
> response shape, impact endpoint) now describe an earlier planned shape
> that has since diverged from what's actually implemented — see
> `backend/app/api/routes/*.py` for the current source of truth. The
> **Repository management** → list/detail entries and the new
> **Source file access** entry below have been brought in line with the
> real implementation as part of adding the frontend product UI, since
> the frontend now depends on them directly; a full pass reconciling the
> rest of this document with the implemented API was out of scope for
> that change and is left as follow-up.

- Base path: `/api/v1`
- Format: JSON request/response bodies
- No authentication in v1 (see [SECURITY.md](SECURITY.md)) — endpoints are
  reachable by any client that can reach the backend process.
- All endpoints except repository creation/listing and `/health` are scoped
  under `/repositories/{repository_id}/...` and must 404 if
  `repository_id` doesn't exist.

## Error format

```json
{
  "error": {
    "code": "REPOSITORY_NOT_FOUND",
    "message": "No repository with id 3f9c...e1 exists."
  }
}
```

Standard HTTP status codes apply (400 validation, 404 not found, 409
conflict — e.g. reindexing while an ingestion is already running, 500
unhandled).

## Health

### `GET /api/v1/health`

Liveness check. Returns `{"status": "ok"}`. Does not check downstream store
connectivity in v1. See also `GET /api/v1/health/live` (equivalent,
dependency-free liveness) and `GET /api/v1/health/ready` (per-dependency
readiness — Neo4j, Chroma, database, embedding model, LLM).

## Repository management

### `POST /api/v1/repositories`

Registers and ingests a new repository.

Request:
```json
{
  "name": "billing-service",
  "source_type": "git_url",
  "source_location": "https://github.com/example/billing-service.git",
  "default_branch": "main"
}
```
`source_type` is `local_path` or `git_url`. When `local_path`,
`source_location` must resolve inside a configured allow-listed base
directory (see [SECURITY.md](SECURITY.md)).

Response `202 Accepted`:
```json
{
  "repository_id": "3f9c1a2e-...-e1",
  "name": "billing-service",
  "status": "pending"
}
```

### `POST /api/v1/repositories/clone`

Clones a public HTTPS Git repository and runs the full ingestion
pipeline (parse → graph → vector index) synchronously, returning the
finished `RepositoryResponse` (same shape as `/upload` below). This is
the real, implemented shape for URL-based import — it supersedes the
`POST /api/v1/repositories` sketch above for `source_type: "git_url"`.

Request:
```json
{
  "name": "billing-service",
  "git_url": "https://github.com/example/billing-service.git",
  "branch": "main"
}
```
`branch` is optional (defaults to the repository's default branch).

Response `201 Created`: a `RepositoryResponse` (see `GET /repositories`
below for the shape), with `source_type: "git_url"` and
`source_location` set to `git_url`.

Restrictions (see [SECURITY.md](SECURITY.md) "Repository acquisition
safety"):
- **HTTPS only.** `ssh://`, scp-style (`git@host:path`), `file://`, and
  URLs with embedded credentials are rejected with `400 INVALID_GIT_URL`.
- **Host allow-list.** Only hosts in `REPO_CLONE_ALLOWED_HOSTS` (default
  `github.com,gitlab.com`) are accepted — any other host is rejected
  with `400 GIT_HOST_NOT_ALLOWED` before `git` is invoked.
- **Public repositories only.** Private repositories are not supported
  in this version (no credential/token input exists).
- **Feature toggle.** If `REPO_URL_CLONE_ENABLED=false`, every call
  fails with `403 GIT_CLONING_DISABLED` regardless of the URL.
- Size/time bounds from `INGESTION_MAX_REPO_SIZE_MB` /
  `INGESTION_CLONE_TIMEOUT_SECONDS` apply, same as any other ingestion.

### `POST /api/v1/repositories/upload`

Uploads a `.zip` file (multipart form: `name`, `file`) and runs the same
synchronous ingestion pipeline as `/clone` above. Response shape and
status code are identical.

### `GET /api/v1/repositories`

Lists all registered repositories (`RepositoryResponse[]`, newest first).
Added for the dashboard's repository list — reuses the existing
`list_repositories` store function, no new persistence.

Response `200`:
```json
[
  {
    "repository_id": "3f9c...",
    "name": "billing-service",
    "source_type": "git_url",
    "source_location": "https://github.com/example/billing-service.git",
    "status": "ready",
    "default_branch": "main",
    "commit_sha": "a1b2c3d4...",
    "file_count": 128,
    "error_message": null,
    "file_stats": null,
    "created_at": "2026-07-30T09:55:00Z",
    "last_indexed_at": "2026-07-30T10:00:00Z"
  }
]
```

Per-repository *analysis* status (parser/graph/vector subsystem status,
progress, node/chunk counts) is a separate concern — see
`GET /repositories/{repository_id}/analysis`, not duplicated here.

### `GET /api/v1/repositories/{repository_id}`

Returns the same `RepositoryResponse` shape as one list item above, for a
single repository. `404 NOT_FOUND` if `repository_id` doesn't exist.
Added for the repository overview page and the sidebar's repository
context (name, source, file count) — analysis/graph/vector status is
fetched separately from `/analysis`, which is polled/streamed while an
analysis is running.

### `DELETE /api/v1/repositories/{repository_id}`

Deletes the repository's SQLite record, its Neo4j subgraph (all nodes with
that `repository_id`), and its ChromaDB collection. Irreversible.

Response `204 No Content`.

### `POST /api/v1/repositories/{repository_id}/reindex`

Re-runs ingestion for an already-registered repository (re-clone/re-read,
re-parse, re-write graph, re-embed changed chunks). Returns `409` if an
ingestion is already in progress for that repository.

Response `202 Accepted`:
```json
{"repository_id": "3f9c...", "status": "pending"}
```

### `GET /api/v1/repositories/{repository_id}/files/source`

Returns a line-range snippet of one file inside the repository's ingested
workspace. Added for the frontend's source-code viewer — citation
click-through, graph node "View Source", and impact-row "View Source" all
call this rather than the frontend attempting to fetch raw repository
files itself. See [SECURITY.md](SECURITY.md) "Source file access" for the
path-traversal defenses this endpoint applies.

Query parameters:

| Param | Meaning |
|---|---|
| `path` | Repository-relative file path (required) |
| `start_line` | 1-indexed start line (optional) |
| `end_line` | 1-indexed end line (optional; defaults to `start_line`) |

When `start_line`/`end_line` are omitted, returns a bounded prefix of the
file (first ~400 lines) rather than the whole file. When given, returns
that range padded with a few lines of surrounding context.

Response `200`:
```json
{
  "repository_id": "3f9c...",
  "file_path": "app/services/billing.py",
  "start_line": 37,
  "end_line": 63,
  "total_lines": 210,
  "content": "class InvoiceService:\n    ...\n",
  "truncated": false
}
```

Errors: `400 VALIDATION_ERROR` for a path that escapes the repository
workspace (absolute path or `..` traversal) or a file over the 2MB size
cap; `404 NOT_FOUND` if the repository or file doesn't exist.

## Graph exploration

### `GET /api/v1/repositories/{repository_id}/graph`

Returns a subgraph for visualization (Cytoscape.js-consumable shape).

Query parameters:

| Param | Meaning |
|---|---|
| `root` | Qualified name of a node to center on (optional; omit for a repo-wide overview capped at a default node limit) |
| `depth` | Traversal depth from `root` (default 1) |
| `node_types` | Comma-separated filter, e.g. `Class,Function,Method` |

Response `200`:
```json
{
  "nodes": [
    {"id": "app.services.billing.InvoiceService", "type": "Class", "label": "InvoiceService", "file_path": "app/services/billing.py", "start_line": 10, "end_line": 60}
  ],
  "edges": [
    {"source": "app.services.billing.InvoiceService.charge", "target": "app.services.gateway.PaymentGateway.submit", "type": "CALLS"}
  ]
}
```

### `GET /api/v1/repositories/{repository_id}/symbols?q=charge`

Symbol search/autocomplete over graph node qualified names and names, used
by the frontend to let a user pick a target for Q&A scoping or impact
analysis.

Response `200`:
```json
{
  "results": [
    {"qualified_name": "app.services.billing.InvoiceService.charge", "type": "Method", "file_path": "app/services/billing.py", "start_line": 42}
  ]
}
```

## Retrieval / Q&A

### `POST /api/v1/repositories/{repository_id}/query`

Hybrid RAG question-answering endpoint.

Request:
```json
{
  "question": "What does InvoiceService.charge do and what does it call?"
}
```

Response `200`:
```json
{
  "answer": "InvoiceService.charge (app/services/billing.py:42-58) validates the amount and calls PaymentGateway.submit (app/services/gateway.py:15-30) to process payment.",
  "citations": [
    {"file_path": "app/services/billing.py", "start_line": 42, "end_line": 58, "qualified_name": "app.services.billing.InvoiceService.charge"},
    {"file_path": "app/services/gateway.py", "start_line": 15, "end_line": 30, "qualified_name": "app.services.gateway.PaymentGateway.submit"}
  ],
  "retrieval_mode": "hybrid"
}
```

Every item in `citations` must correspond to a chunk or graph node actually
returned by GraphRetriever/VectorRetriever for this request (see
[AGENTS.md](AGENTS.md) rule 5, [ARCHITECTURE.md](ARCHITECTURE.md)). If the
LLM's draft answer cites something outside that set, the backend
regenerates or strips the unsupported citation rather than returning it.

## Change-impact analysis

### `POST /api/v1/repositories/{repository_id}/impact`

Request (target given by qualified name, or by file + line):
```json
{
  "qualified_name": "app.services.billing.InvoiceService.charge",
  "max_depth": 3
}
```
or
```json
{
  "file_path": "app/services/billing.py",
  "line": 45,
  "max_depth": 3
}
```

Response `200`:
```json
{
  "target": {
    "qualified_name": "app.services.billing.InvoiceService.charge",
    "file_path": "app/services/billing.py",
    "start_line": 42,
    "end_line": 58
  },
  "impacted": [
    {
      "qualified_name": "app.api.routes.invoices.charge_invoice",
      "type": "Function",
      "file_path": "app/api/routes/invoices.py",
      "start_line": 20,
      "end_line": 28,
      "relationship_path": ["CALLS"],
      "depth": 1
    },
    {
      "qualified_name": "POST /invoices/{id}/charge",
      "type": "APIEndpoint",
      "file_path": "app/api/routes/invoices.py",
      "start_line": 18,
      "end_line": 19,
      "relationship_path": ["HANDLED_BY", "CALLS"],
      "depth": 2
    }
  ],
  "summary": "Changing InvoiceService.charge directly affects the charge_invoice route handler, and transitively the POST /invoices/{id}/charge API endpoint.",
  "generated_at": "2026-08-03T12:00:00Z"
}
```

`impacted` is produced entirely by deterministic graph traversal; `summary`
is the only LLM-generated field and must not introduce entries that are not
in `impacted` (see [AGENTS.md](AGENTS.md) rule 2,
[ARCHITECTURE.md](ARCHITECTURE.md)).

## Versioning

The `/api/v1` prefix is the only version in scope for the MVP. Breaking
changes to response shapes before a stable release are expected to be
documented here in the same change that makes them, per
[AGENTS.md](AGENTS.md).

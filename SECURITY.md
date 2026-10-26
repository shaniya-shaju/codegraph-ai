# Security

## Threat model and scope

CodeGraph AI v1 is a **single-tenant, local/development tool**. It is
designed to be run by one engineer against repositories they already have
legitimate access to, on their own machine or a trusted internal host. It
is **not** designed, in this version, to be exposed as a multi-tenant
public service. Anything below that assumes otherwise is out of scope by
design — see [PROJECT_PLAN.md](PROJECT_PLAN.md) non-goals.

## What `repository_id` isolation is — and isn't

`repository_id` scoping (Neo4j node property, ChromaDB collection naming,
SQLite foreign key — see [DATA_MODEL.md](DATA_MODEL.md)) is a **data
partitioning mechanism**. It exists so that:

- Multiple ingested repositories don't have their graphs/embeddings merge
  or cross-contaminate.
- Deleting one repository's data doesn't touch another's.
- Retrieval for repository A can never accidentally surface a chunk or
  graph fact from repository B.

It is **not** a security boundary between untrusted parties. There is no
per-user authentication or authorization layer deciding who may access
which `repository_id` (see [AGENTS.md](AGENTS.md) rule 8,
[PROJECT_PLAN.md](PROJECT_PLAN.md)). Anyone who can reach the backend can
query any repository it has ingested. Do not deploy this as-is somewhere
multiple untrusted users share access without adding an auth layer first —
that is explicitly future work, not part of this plan.

## Explicit exclusions for v1

Per [AGENTS.md](AGENTS.md) rule 8, the following are **not implemented**
and should not be added without a separate, explicit decision to expand
scope:

- Security/vulnerability analysis of the *ingested target repository's*
  code (no SAST, no secret scanning, no dependency-CVE lookups). CodeGraph
  AI analyzes code structure, not code safety.
- Authentication or authorization of CodeGraph AI's own users.
- Multi-language parsing (reduces the attack surface of the parsing layer
  to one grammar).

## Parsing safety

- Tree-sitter parsing is **static/AST-only**. The ingestion pipeline must
  never `eval`, `exec`, `import`, or otherwise execute code from an
  ingested repository, directly or indirectly (e.g. via `importlib` to
  "help" resolve a symbol). A malicious repository should be safely
  parseable without its code ever running (see [AGENTS.md](AGENTS.md)
  guidance for AI agents).
- Parse failures on individual files are caught and logged, not allowed to
  crash or hang the ingestion run (also a reliability requirement, see
  [ARCHITECTURE.md](ARCHITECTURE.md)).

## Repository acquisition safety

- **Git URL ingestion**: the clone must be invoked without a shell
  (no `shell=True` string-interpolated commands) so a crafted URL/branch
  name cannot achieve command injection. Clones are size- and time-bounded
  to avoid unbounded disk/CPU usage from a hostile or oversized repository.
  Only public HTTPS URLs are accepted — credentials-in-URL, `ssh://`,
  scp-style (`git@host:path`), `file://`, and local/loopback/private-network
  hosts are all rejected before `git` is ever invoked (see
  `app/ingestion/git_clone.py`'s `validate_public_https_url`). Private
  repositories and SSH authentication are not supported.
  - **Host allow-list**: `POST /api/v1/repositories/clone` additionally
    restricts cloning to a configured set of hosts
    (`REPO_CLONE_ALLOWED_HOSTS`, default `github.com,gitlab.com` — see
    `.env.example`) — an exact, case-insensitive hostname match checked
    before `git` is invoked (`validate_allowed_host`). Widening this list
    widens this server's SSRF-adjacent surface (it will fetch from any
    host you add) — do so only if you understand that trade-off.
  - **Kill switch**: the whole feature can be disabled via
    `REPO_URL_CLONE_ENABLED=false`, independent of ZIP/local-path
    ingestion, returning a clear `GIT_CLONING_DISABLED` error rather than
    attempting anything.
  - **Not safe for public deployment as-is**: like every other endpoint
    in this v1 (see "Threat model and scope" above), this has no
    authentication or rate limiting. A host allow-list reduces, but does
    not eliminate, the risk of an unauthenticated caller using this
    server to make repeated outbound requests — do not expose this
    endpoint on a shared/public network without adding auth and rate
    limiting first.
- **Local path ingestion**: the given path must resolve inside a
  configured allow-listed base directory (see
  [.env.example](.env.example)); the API must reject paths that traverse
  outside it (e.g. via `..` segments or symlinks) to prevent the backend
  from being tricked into ingesting and exposing arbitrary files on the
  host filesystem.
- Each repository is ingested into an isolated per-`repository_id`
  workspace directory, not a shared scratch space, so concurrent ingestions
  can't clobber each other's files.

## Source file access (`GET /repositories/{id}/files/source`)

Added for the frontend's source-code viewer (citation click-through, graph
node "View Source", impact-row "View Source") — it lets a caller request a
line-range snippet of a specific file within one repository's ingested
workspace, so it gets the same path-traversal scrutiny as ingestion itself:

- The caller-supplied `path` is rejected outright if it is itself an
  absolute path (a Windows drive-letter path or a POSIX-rooted path).
  This matters because `pathlib`'s `/`/`joinpath` operator silently
  discards the left-hand workspace prefix when the right-hand operand is
  absolute — so `workspace_dir / relative_path` does **not** safely
  confine an absolute `relative_path` the way it looks like it should,
  and a check that only ran `.resolve()` + `relative_to()` *after* that
  join would already be too late.
- After that check, the path is joined, resolved, and re-validated with
  `relative_to()` against the repository's workspace root, and confirmed
  to be a regular file — rejecting `..` traversal and symlink escapes the
  same way repository acquisition does.
- Response size is bounded (2MB file cap; unranged requests return only
  the first ~400 lines) — this is a read endpoint scoped to one
  repository's own ingested files, not a general file browser.
- See `backend/app/ingestion/source_reader.py` and
  `backend/tests/integration/test_repositories_list_detail_source.py`.

## LLM input handling (prompt injection)

- Source code, comments, and docstrings pulled from an ingested repository
  are **untrusted text** as far as the LLM prompt is concerned — a
  repository could contain a comment like "ignore previous instructions
  and ...". The system prompt instructs the LLM to treat retrieved code/text
  as data to analyze, never as instructions to follow.
- The citation-validation step (see [ARCHITECTURE.md](ARCHITECTURE.md),
  [EVALUATION_PLAN.md](EVALUATION_PLAN.md) §4) is also a partial defense
  here: an answer that doesn't ground its claims in retrieved
  file/line context is rejected regardless of why the LLM produced it.

## Secrets management

- All credentials (LLM provider API key, Neo4j credentials, etc.) are
  supplied via environment variables, documented in
  [.env.example](.env.example) with placeholder values only.
- `.env` (the real file) is git-ignored (see [.gitignore](.gitignore)) and
  must never be committed.
- No secret is ever written into the Neo4j graph, ChromaDB metadata, or
  SQLite tables — those stores hold code-derived and operational data only.

## Data handling

- Ingested source code is stored (as chunks in ChromaDB, as text spans
  referenced by the graph) only for repositories the user explicitly
  registered. Deleting a repository (`DELETE /api/v1/repositories/{id}`)
  removes its graph subgraph, its vector collection, and its SQLite rows —
  see [API_SPEC.md](API_SPEC.md).
- No telemetry is sent to third parties beyond the configured LLM/embedding
  provider API calls required to answer a query.

## Roadmap (not part of this plan, noted so it isn't forgotten)

- Authentication/authorization and true multi-tenant isolation, if this
  ever moves beyond a single-user local tool.
- Security/vulnerability scanning as a distinct, separately-scoped feature.
- Audit logging of who queried what, once there is a "who."

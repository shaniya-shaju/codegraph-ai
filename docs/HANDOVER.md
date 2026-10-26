# Handover Guide

This document is written for someone receiving this repository who did
not build it — a new developer, or a different team/organization taking
it over. It should be enough, together with [.env.example](../.env.example)
and [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md), to get CodeGraph AI running
without reading or editing any application source code.

## What CodeGraph AI does

CodeGraph AI is a source-code intelligence tool for Python repositories.
Point it at a repository (upload a ZIP or give it a public Git URL) and
it:

1. Parses the code with Tree-sitter and builds a **knowledge graph**
   (Neo4j) of files, classes, functions, calls, imports, and API
   endpoints.
2. Chunks and embeds the code into a **vector store** (ChromaDB) for
   semantic search.
3. Answers natural-language questions about the codebase, grounded in
   that graph + vector evidence, with file/line citations on every claim
   an LLM makes (see [ARCHITECTURE.md](../ARCHITECTURE.md) and
   [AGENTS.md](../AGENTS.md) rule 2 — the LLM explains evidence, it never
   invents a code relationship the graph doesn't contain).
4. Computes **deterministic change-impact analysis** — everything that
   transitively depends on a given function/class/endpoint — via graph
   traversal, with an optional LLM-written natural-language summary
   layered on top, clearly separated from the deterministic result.
5. Visualizes the graph and the impact analysis in a React UI.

## Architecture

| Component | Technology | Role |
|---|---|---|
| Frontend | React + TypeScript + Vite | Dashboard, Assistant chat, Graph explorer, Impact analysis UI |
| Backend | Python 3.12 + FastAPI | REST API, ingestion, retrieval, answer generation, impact analysis |
| Knowledge graph | Neo4j (Docker) | Code structure ground truth |
| Vector store | ChromaDB (embedded) | Semantic code search |
| Application database | SQLite | Repositories, analysis runs, conversations |
| Embedding model | `sentence_transformers` (local) | Turns code into vectors |
| LLM | Anthropic (cloud) or LM Studio (local) | Answer/summary generation only |

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full system design and
[DATA_MODEL.md](../DATA_MODEL.md) for the Neo4j/SQLite/Chroma schemas.

## Required software

- **Git**
- **Docker Desktop** (or Docker Engine + the Compose plugin) — runs
  Neo4j, and optionally the backend/frontend too
- **Python 3.12** — only needed if you want to run the backend outside
  Docker, or run the smoke-test scripts in this document
- **Node.js 20+** — only needed if you want to run the frontend outside
  Docker
- **LM Studio** (optional) — only needed if you want a fully local LLM
  instead of a cloud provider; see [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md)

**Host-script dependency note:** every `python scripts/*.py` script in
this document (`check_environment.py`, `seed_demo_repository.py`,
`run_demo_checks.py`, etc.) imports the backend application directly —
they are not standalone tools. Running any of them on your host (outside
Docker) requires the backend's own Python dependencies to already be
installed in your active Python environment first (`make setup-backend`,
or the manual `pip install -e ".[dev]"` steps in
[HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) on Windows) — a bare
system Python without those installed will fail with `ModuleNotFoundError`
before the script does anything useful.

## First-time setup

```bash
git clone <this-repository-url>
cd codegraph-ai   # or whatever the clone directory is named
cp .env.example .env
```

Then decide on an LLM provider before starting anything — see
"Configuration" below. If you're going local, also do LOCAL_LLM_SETUP.md
steps 1-4 (install LM Studio, download/load a model, start its local
server) before continuing.

## Configuration

Every setting lives in `.env` (copied from [.env.example](../.env.example)),
organized into sections: APPLICATION, DATABASE, WORKSPACE, NEO4J, CHROMA,
EMBEDDINGS, LLM (+ LM STUDIO), RETRIEVAL, IMPACT. Each variable there is
commented with whether it's required/optional and its default — read that
file before asking "what do I need to change?"; the two things nearly
everyone changes are:

```env
# Pick one:
LLM_PROVIDER=anthropic          # cloud — also set LLM_API_KEY to a real key
# or
LLM_PROVIDER=lmstudio           # local, zero-cost — also set LLM_BASE_URL and
                                 # LLM_MODEL, see LOCAL_LLM_SETUP.md
# or
LLM_PROVIDER=openai_compatible  # any other OpenAI-compatible cloud API, e.g.
                                 # DeepSeek — also set LLM_BASE_URL/LLM_MODEL/
                                 # LLM_API_KEY, see .env.example's DEEPSEEK section
```

DeepSeek (and similarly-shaped providers) need no special code path — the
backend's `openai_compatible` provider is already generic (see
`backend/app/rag/llm_provider.py`); LM Studio is just the local instance
of the same thing. See `.env.example`'s "DEEPSEEK" section for the exact
variables. Whichever `LLM_PROVIDER` you choose, it's used **only for
answer generation and impact summaries** — embeddings always stay on the
local `sentence_transformers` provider regardless.

Never commit your real `.env` — see [SECURITY.md](../SECURITY.md).

## Starting the application

```bash
docker compose up -d
docker compose ps   # neo4j and backend should become "healthy"
```

This starts Neo4j, the backend, and the frontend dev server, all via
Docker (see [.env.example](../.env.example) and
`docker-compose.yml`). LM Studio, if you're using it, is **not**
containerized — it's a normal application on your host; see
[LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md) for why and how the backend
reaches it from inside Docker.

Verify readiness:

```bash
curl http://localhost:8000/api/v1/health/live    # process is up (always fast)
curl http://localhost:8000/api/v1/health/ready   # per-dependency status (Neo4j, Chroma, DB, embedding model, LLM)
```

On Windows PowerShell, use `curl.exe` (plain `curl` there is a `curl.exe`-incompatible
`Invoke-WebRequest` alias and will not behave the same way):

```powershell
curl.exe http://localhost:8000/api/v1/health/live
curl.exe http://localhost:8000/api/v1/health/ready
```

or run the full check:

```bash
python scripts/check_environment.py
```

Open the frontend at http://localhost:5173.

### Local backend vs Docker backend

If you'd rather run the backend directly on your machine (e.g. for
faster iteration while developing) instead of in Docker, the only things
that differ are hostnames/ports — everything else in `.env` is unchanged.

**Neo4j port note:** inside its container, Neo4j always listens on the
standard ports (7474 browser, 7687 bolt). This repo's `docker-compose.yml`
publishes those to **remapped host ports** — 7475 (browser) and **7688**
(bolt) — because 7474/7687 are already used by another local container on
some machines (see `docker-compose.yml`'s `neo4j` service and
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#port-conflict)). A host-run
backend/script connects over the published host port; the containerized
backend connects over the container-internal port via the Docker network:

| | Local (host-run) backend | Docker backend |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7688` (published host port) | `bolt://neo4j:7687` (container-internal port, already set by `docker-compose.yml`, don't change it) |
| Neo4j Browser | `http://localhost:7475` | n/a (same URL either way — it's your host browser hitting the published port) |
| `LLM_BASE_URL` (if using LM Studio) | `http://localhost:1234/v1` | `http://host.docker.internal:1234/v1` (already the Docker Compose default) |

To run the backend locally: `make setup-backend && make run-backend`
(still needs Neo4j reachable — `docker compose up -d neo4j` on its own
works fine for this). To run the frontend locally:
`make setup-frontend && make run-frontend`.

**Windows note:** these `make` targets assume a POSIX shell. From plain
PowerShell/cmd.exe (no Git Bash, WSL, or Make installed), run the
underlying commands directly instead — see
[HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) for the full Windows
PowerShell setup and the equivalent `python scripts/*.py` commands for
every `make` target used in this document.

Running the frontend locally (not via `docker compose up`) also needs its
own env file — `cp frontend/.env.example frontend/.env` — since Vite
reads `frontend/.env` directly rather than the root `.env` Docker Compose
uses; the only variable in it, `VITE_API_BASE_URL`, defaults to
`http://localhost:8000` and rarely needs changing.

## Stopping the application

```bash
docker compose down       # stops containers, keeps data (named volumes)
docker compose down -v    # stops containers AND deletes all data — irreversible
```

`make stop` is an alias for `docker compose down`.

## Resetting the demo

```bash
make demo-seed     # imports + fully analyzes sample-repositories/demo-python-app
make demo-check    # exercises retrieval / citations / impact analysis end-to-end
make demo-reset    # removes the demo repository from every store (SQLite, Neo4j, Chroma)
```

No `make`/POSIX shell available (plain Windows PowerShell)? Run the same
scripts these targets call, directly — see "Required software" and the
host-script dependency note below for what needs to be installed first:

```powershell
python scripts/seed_demo_repository.py
python scripts/run_demo_checks.py
python scripts/reset_demo.py
```

`demo-check` uses a fake LLM (no real API key needed) so it can verify
the retrieval/citation/impact pipeline without depending on LLM
availability — see `scripts/run_demo_checks.py`'s own docstring. To
verify the demo with your *real* configured LLM instead, ask it a
question through the Assistant UI, or `python scripts/check_llm.py`
first and then the same question via `curl`/the UI.

## Importing a repository from a URL

Besides uploading a ZIP, the Dashboard's **Import Repository → Clone Git
Repository** tab (or `POST /api/v1/repositories/clone`) lets you paste a
public GitHub or GitLab HTTPS URL and have the backend clone + fully
index it in one step — no local checkout needed first.

- **Public repositories only** — no SSH, no credentials, no private
  repos. This is deliberate, not a current limitation to work around
  (see [SECURITY.md](../SECURITY.md) "Repository acquisition safety").
- Restricted by default to `github.com`/`gitlab.com`
  (`REPO_CLONE_ALLOWED_HOSTS`) and can be disabled entirely
  (`REPO_URL_CLONE_ENABLED=false`) — see
  [ENVIRONMENT.md](ENVIRONMENT.md#cloning-a-repository-from-a-url--security-sensitive-read-before-changing)
  for every related setting.
- See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#clone-a-repository-from-a-url-errors)
  for what each error (`GIT_CLONING_DISABLED`, `GIT_HOST_NOT_ALLOWED`,
  `INVALID_GIT_URL`, `GIT_CLONE_FAILED`) means.
- **Not safe for public/shared deployment as-is** — see "Before public
  hosting" below. This endpoint has no authentication; the host
  allow-list narrows but does not remove the risk of an unauthenticated
  caller triggering repeated outbound clones from your server.

## Changing the LLM

Edit `LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY`/`LLM_BASE_URL` in `.env`,
then restart the backend (`docker compose restart backend`, or just
re-run `make run-backend` if running locally — settings are read once at
process start). No code changes, no data migration — the LLM is stateless
between requests (see `backend/app/rag/llm_provider.py`). Verify with:

```bash
python scripts/check_llm.py
```

See [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md) for the local path in full.

## Changing the embedding model

Edit `EMBEDDING_MODEL_NAME` (and `EMBEDDING_TRUST_REMOTE_CODE` if the new
model needs it — see `.env.example`) in `.env`, restart the backend, then
verify:

```bash
python scripts/check_embeddings.py
```

**Important:** changing the embedding model changes the vector space —
existing repositories' Chroma collections were embedded with the *old*
model and will not be directly comparable. Re-analyze (reindex) every
repository after switching (see "Stale repository index" in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md); a full reindex is the
Reanalyze action on each repository's overview page, or
`POST /api/v1/repositories/{id}/analyze` with `{"force": true}`).

## Backing up Neo4j / Chroma / SQLite

All three data stores live under the `backend_data` Docker volume (or the
repository root's `data/` directory if running the backend locally —
resolved there regardless of which directory you launch the backend or a
script from) plus Neo4j's own `neo4j_data`/`neo4j_logs` volumes:

| Store | Docker volume | Local path |
|---|---|---|
| SQLite (repositories, analysis state, conversations) | `backend_data:/data/codegraph.db` | `data/codegraph.db` (repo root) |
| ChromaDB (vector index) | `backend_data:/data/chroma` | `data/chroma/` (repo root) |
| Neo4j (graph) | `neo4j_data:/data` | n/a (always containerized) |

To back up: stop the stack (`docker compose down`, without `-v`) and copy
the Docker volumes' contents (`docker run --rm -v codegraph_backend_data:/data -v $(pwd):/backup alpine tar czf /backup/backend_data.tar.gz -C /data .`,
adjusting the volume name for your Compose project prefix — see `docker
volume ls`), or copy the repo root's `data/` directly if running locally.
Restore by reversing the same copy before starting the stack again.

## Updating the project

```bash
git pull
make setup                # reinstall backend + frontend dependencies
docker compose build      # rebuild the backend image if its Dockerfile/deps changed
docker compose up -d
```

Neo4j's Docker image is pinned to a specific version in
`docker-compose.yml` (not `latest`) so updates never happen implicitly —
bump that tag deliberately (and check the
[Neo4j upgrade documentation](https://neo4j.com/docs/upgrade-migration-guide/current/)
for any migration steps) if you want a newer Neo4j.

## Running tests

```bash
make test-unit          # backend unit tests — no external dependencies needed
make test-integration    # backend integration tests — most gracefully skip without a reachable Neo4j
make test-e2e            # full demo workflow — needs a reachable Neo4j
make test-frontend       # frontend unit/component tests (Vitest)
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full test/lint/typecheck
matrix expected to stay green.

## Production cautions

This project's v1 scope is explicitly a single-tenant, local/dev tool —
see [PROJECT_PLAN.md](../PROJECT_PLAN.md) and [SECURITY.md](../SECURITY.md)
"Explicit exclusions for v1." Before running it anywhere beyond your own
machine or a trusted internal network:

- **No authentication exists.** Anyone who can reach the backend's port
  can read/import/delete any repository it manages.
- **`CORS_ALLOWED_ORIGINS` must never be `*`** — it's paired with
  `allow_credentials: true`, which browsers reject for a wildcard origin
  anyway, but don't rely on that; set it to the real frontend origin(s).
- **Change every placeholder credential** (`NEO4J_PASSWORD`,
  `LLM_API_KEY`) from the `.env.example` defaults before any shared use.
- **Git/ZIP ingestion has size and timeout limits** (`INGESTION_MAX_*`,
  `INGESTION_CLONE_TIMEOUT_SECONDS`) but is still fetching/executing
  external, untrusted repository content — see SECURITY.md's threat
  model for exactly what is and isn't in scope.
- **The LLM's answers are not guaranteed correct** even with citation
  grounding — citations point at real evidence the model claimed to use,
  which is a strong signal but not a formal proof the explanation is
  accurate. Treat answers as a starting point, not ground truth.

### Before public hosting — security checklist

A short, concrete version of the cautions above. This project is **not**
ready for public/multi-tenant hosting as-is — see
[SECURITY.md](../SECURITY.md) for the full threat model and explicit
exclusions. Do not expose this beyond your own machine or a trusted
internal network without at least:

- [ ] Add a real authentication/authorization layer in front of the API
      — none exists today (see SECURITY.md "What `repository_id`
      isolation is — and isn't").
- [ ] Set `NEO4J_PASSWORD` and `LLM_API_KEY` to real, non-placeholder
      values — never ship with `changeme`.
- [ ] Set `CORS_ALLOWED_ORIGINS` to the exact real frontend origin(s) —
      never `*`.
- [ ] Put the stack behind TLS (a reverse proxy terminating HTTPS) —
      nothing in this project terminates TLS itself.
- [ ] Re-check `INGESTION_MAX_REPO_SIZE_MB`/`INGESTION_MAX_UPLOAD_SIZE_MB`/
      `INGESTION_CLONE_TIMEOUT_SECONDS` are sized for a multi-user,
      internet-facing load, not just a single developer's convenience.
- [ ] Confirm no `.env`, real API key, or credential is baked into any
      Docker image or committed to version control (see
      "Before GitLab push checklist" in
      [HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md)).
- [ ] Accept that there is still no audit logging, rate limiting, or
      per-user quota — a single caller can read/import/delete any
      repository the backend manages. This is an explicit v1 non-goal,
      not an oversight (see PROJECT_PLAN.md).
- [ ] If keeping URL-based repository cloning enabled
      (`REPO_URL_CLONE_ENABLED=true`), understand it lets an
      unauthenticated caller make this server fetch from any host on
      `REPO_CLONE_ALLOWED_HOSTS` repeatedly, with no rate limiting — an
      SSRF-adjacent surface the host allow-list narrows but does not
      close. Consider setting `REPO_URL_CLONE_ENABLED=false` until real
      auth/rate-limiting exists.

If any box above isn't checked, treat this as local/dev-only, full stop.

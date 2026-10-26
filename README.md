# CodeGraph AI

**Graph-Augmented RAG for Source-Code Understanding and Change-Impact Analysis**

CodeGraph AI helps engineers understand unfamiliar Python codebases and reason
about the blast radius of a change. It combines deterministic source-code
parsing, a knowledge graph of code structure, vector-based semantic search,
and an LLM — so that answers are grounded in facts extracted from the code
itself, not in the LLM's guesses.

> Status: **full-stack v1** — parsing, graph construction, vector indexing,
> hybrid retrieval, grounded Q&A with citations, deterministic
> change-impact analysis, a React product UI (dashboard, chat assistant,
> Cytoscape graph explorer, impact analysis), and full-stack reliability/
> demo tooling. Supports a cloud LLM (Anthropic, or any other
> OpenAI-compatible cloud API such as DeepSeek) and a fully local LLM via
> [LM Studio](docs/LOCAL_LLM_SETUP.md) — see
> [docs/HANDOVER.md](docs/HANDOVER.md) for the complete setup guide and
> [PROJECT_PLAN.md](PROJECT_PLAN.md) for full scope.

## Why

Large language models are good at explaining code in natural language but
unreliable at knowing *exactly* which functions call which, which modules
depend on which packages, or what breaks if a function's signature changes.
CodeGraph AI fixes this by never asking the LLM to invent structural facts:

- **Tree-sitter** deterministically parses Python source into an AST.
- A **knowledge graph (Neo4j)** stores the resulting entities (files,
  classes, functions, parameters, ...) and their relationships (calls,
  imports, extends, ...) as ground truth.
- A **vector store (ChromaDB)** indexes code chunks for semantic
  ("meaning-based") retrieval.
- **LangChain** orchestrates retrieval (graph + vector) and hands the LLM a
  citation-bearing context to generate an answer — the LLM only explains and
  summarizes, it never asserts a relationship the graph doesn't contain.

## What it does (MVP)

1. Ingests a single Python repository (local path or Git URL).
2. Parses it with Tree-sitter and builds a code knowledge graph in Neo4j.
3. Chunks and embeds the code into ChromaDB for semantic search.
4. Answers natural-language questions about the codebase via hybrid
   (graph + vector) retrieval, with file path and line-number citations on
   every answer.
5. Given a function, class, or file, computes the **change-impact set** —
   everything in the repository that transitively depends on it — using
   deterministic graph traversal, with an LLM-generated natural-language
   summary layered on top.
6. Visualizes the code graph and impact analysis in a React + Cytoscape.js
   UI.

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for full MVP scope and explicit
non-goals.

## Recommended demo path

Ingestion, graph construction, vector indexing, search, and deterministic
impact analysis all work **without any paid API key**. Only the Assistant
chat Q&A and LLM-written impact summaries need an LLM configured. Pick
whichever of these fits:

| Path | What it needs | What you get |
|---|---|---|
| **Zero-cost (LM Studio)** | [LM Studio](https://lmstudio.ai/) installed, a local chat model loaded — see [docs/LOCAL_LLM_SETUP.md](docs/LOCAL_LLM_SETUP.md) | Full live Q&A and impact summaries, fully offline, no billing |
| **Paid/cloud (Anthropic)** | A real `LLM_API_KEY` for `LLM_PROVIDER=anthropic` | Full live Q&A and impact summaries via the cloud |
| **Low-cost cloud (DeepSeek, or any OpenAI-compatible API)** | A real API key, `LLM_PROVIDER=openai_compatible` — see `.env.example`'s "DEEPSEEK" section | Same as above, usually cheaper than Anthropic |
| **No key (`make demo-check`)** | Nothing — works with `.env` unchanged from `.env.example` (`LLM_API_KEY=changeme`) | Proves the whole retrieval/citation/impact pipeline end-to-end via a built-in fake LLM; no live chat answers |

New to this repo? [docs/HANDOVER_CHECKLIST.md](docs/HANDOVER_CHECKLIST.md)
is a tick-through checklist covering all four paths, plus a
["before GitLab push"](docs/HANDOVER_CHECKLIST.md#18-before-gitlab-push-checklist)
checklist and a
["before public hosting"](docs/HANDOVER_CHECKLIST.md#19-before-public-hosting-security-checklist)
security checklist. For a ready-to-run demo script with specific
questions to ask, see [docs/DEMO.md](docs/DEMO.md).

## Documentation map

| Document | Contents |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules and conventions for anyone (human or AI agent) contributing code to this repo |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | Goal, MVP scope, non-goals, milestones, success criteria |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System components, ingestion/parsing/retrieval/impact-analysis flows |
| [DATA_MODEL.md](DATA_MODEL.md) | Neo4j graph schema, SQLite schema, ChromaDB collection layout |
| [API_SPEC.md](API_SPEC.md) | REST API endpoints and request/response contracts |
| [EVALUATION_PLAN.md](EVALUATION_PLAN.md) | How correctness, retrieval quality, and impact-analysis accuracy are measured |
| [SECURITY.md](SECURITY.md) | Security boundaries, threat model, explicit exclusions |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev environment, coding conventions, testing expectations |
| [docs/HANDOVER.md](docs/HANDOVER.md) | Full setup, configuration, day-to-day operation, and production cautions for a new recipient of this repository |
| [docs/HANDOVER_CHECKLIST.md](docs/HANDOVER_CHECKLIST.md) | Tick-through checklist to get running and demo-ready from a fresh clone, plus pre-push and pre-public-hosting checklists |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Condensed env-variable quick reference (the Neo4j port trap, the four LLM paths) — `.env.example` remains the full source of truth |
| [docs/DEMO.md](docs/DEMO.md) | A ready-to-run demo script with specific questions to ask, tailored to the included sample repository |
| [docs/LOCAL_LLM_SETUP.md](docs/LOCAL_LLM_SETUP.md) | Installing LM Studio, loading a model, and connecting CodeGraph AI to it (local or Docker backend) |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Fixes for the most common setup/runtime problems |

## Technology stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI |
| AI orchestration | LangChain |
| Source-code parsing | Tree-sitter (Python grammar) |
| Knowledge graph | Neo4j (Docker, pinned version) |
| Vector database | ChromaDB |
| Application database | SQLite (MVP) → PostgreSQL (migration path) |
| Embeddings | `sentence_transformers` (local, no external API calls) |
| LLM | Anthropic (cloud), [LM Studio](docs/LOCAL_LLM_SETUP.md) (local), or any OpenAI-compatible cloud API (e.g. DeepSeek) |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Graph visualization | Cytoscape.js |
| Backend testing | Pytest |
| Frontend testing | Vitest |
| Infrastructure | Docker Compose |
| Code quality | Ruff, mypy, ESLint, Prettier |

## Scope for v1

- **Python repositories only.** No multi-language parsing.
- **No security/vulnerability analysis** of the target repository.
- **No authentication** — this is a single-tenant, local/dev tool for now.
- **No microservices** — one FastAPI backend, one frontend, three data
  stores (Neo4j, ChromaDB, SQLite).

Full rationale in [PROJECT_PLAN.md](PROJECT_PLAN.md) and
[SECURITY.md](SECURITY.md).

## Getting started

For the full walkthrough (configuration, changing the LLM/embedding
model, backups, production cautions) see
**[docs/HANDOVER.md](docs/HANDOVER.md)**. This is the fast path.

### Prerequisites

- Git
- Docker Desktop (or a Docker Engine + Compose plugin)
- [LM Studio](https://lmstudio.ai/) — only if you want a local LLM
  instead of a cloud one (see step 3); skip if using
  `LLM_PROVIDER=anthropic` with a real API key instead
- Python 3.12 if you want to run the backend outside Docker

**Windows:** the `make ...` commands below assume a POSIX shell (Git
Bash/WSL, or Make installed). From plain PowerShell/cmd.exe, use the
PowerShell-equivalent command given next to each one, or see
[docs/HANDOVER_CHECKLIST.md](docs/HANDOVER_CHECKLIST.md) for a full
beginner-safe Windows walkthrough (venv setup, every `make` target's
`python scripts/*.py` equivalent, and `curl.exe` usage).

### 1. Clone the repository

```bash
git clone <this-repository-url>
cd codegraph-ai
```

### 2. Copy the environment file

```bash
cp .env.example .env
```

Every variable is documented inline in `.env.example`. At minimum,
decide your LLM provider — see step 3.

### 3. Configure an LLM

Pick one of four paths. This only affects Assistant chat Q&A and
LLM-written impact summaries — it's used **only for answer generation**,
never for embeddings/retrieval, which always run on the local
`sentence_transformers` provider regardless of which LLM you pick (see
[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)).

**DeepSeek API — cheap cloud demo path.** No local install, and
typically much cheaper than Anthropic. Uses the same generic
`openai_compatible` provider LM Studio uses, just pointed at a real cloud
endpoint — see `.env.example`'s "DEEPSEEK" section:

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_API_KEY=<your real DeepSeek API key>
```

**LM Studio — zero-cost local path.** No API key, fully offline once the
model is downloaded — see [docs/LOCAL_LLM_SETUP.md](docs/LOCAL_LLM_SETUP.md)
for full detail:

```bash
# In LM Studio: download + load a chat model, then start its Local
# Server (default port 1234).
```

```env
# In .env:
LLM_PROVIDER=lmstudio
LLM_MODEL=<the model id LM Studio is serving>
LLM_BASE_URL=http://host.docker.internal:1234/v1   # already the default in .env.example
LLM_API_KEY=lm-studio
```

**Anthropic — highest-quality cloud path**, at a higher cost than DeepSeek:

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-5
LLM_API_KEY=<your real API key>
```

**No LLM at all — fake `demo-check` path.** Leave `.env` as copied from
`.env.example` (`LLM_API_KEY=changeme`). This is a **no-key validation
path, not real interactive Q&A** — `make demo-check` (see step 6 below)
proves the retrieval/citation/impact pipeline works end-to-end via a
built-in fake LLM, but the Assistant chat page itself will abstain rather
than answer until you pick one of the three options above.

### 4. Start CodeGraph AI

```bash
docker compose up -d
docker compose ps        # neo4j and backend should become "healthy"
```

This starts Neo4j, the backend, and the frontend. LM Studio (if used)
stays running on your host — it isn't containerized.

### 5. Verify

```bash
python scripts/check_environment.py   # checks SQLite/workspace/Neo4j/Chroma/embeddings/LLM in one go
```

Then open the frontend: **http://localhost:5173**

Or check the API directly:

```bash
curl http://localhost:8000/api/v1/health/live    # process is up (always fast)
curl http://localhost:8000/api/v1/health/ready   # per-dependency status (Neo4j, Chroma, DB, embedding model, LLM)
```

On Windows PowerShell, use `curl.exe` instead of `curl` (plain `curl` is
a PowerShell alias for `Invoke-WebRequest` with different syntax):

```powershell
curl.exe http://localhost:8000/api/v1/health/live
curl.exe http://localhost:8000/api/v1/health/ready
```

### 6. Seed the demo repository (optional)

A small, hand-written sample application
([sample-repositories/demo-python-app](sample-repositories/demo-python-app))
is included specifically for demonstrating retrieval, grounded Q&A, and
change-impact analysis end-to-end:

```bash
make demo-seed     # imports + fully analyzes the demo repository
make demo-check    # exercises retrieval / citations / impact analysis, prints PASS/FAIL
```

No `make` (plain PowerShell)? Run the same scripts directly — needs the
backend's dependencies installed first, see
[docs/HANDOVER_CHECKLIST.md](docs/HANDOVER_CHECKLIST.md) step 1:

```powershell
python scripts/seed_demo_repository.py
python scripts/run_demo_checks.py
```

Then open it in the frontend (Dashboard → the seeded repository →
Assistant) and ask, for example, "Where is authentication implemented?" —
or via the API (the real path is `/api/v1/...`, always use it in full):

```bash
curl -X POST http://localhost:8000/api/v1/repositories/<repository_id>/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Where is authentication implemented?"}'
```

On Windows PowerShell, use `curl.exe`:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/repositories/<repository_id>/query `
  -H "Content-Type: application/json" `
  -d '{"question":"Where is authentication implemented?"}'
```

(`<repository_id>` is printed by `make demo-seed` /
`seed_demo_repository.py`.)

### Stop

```bash
make stop
```
No `make`? `docker compose down` directly.

### Run tests

```bash
make setup            # install backend + frontend dependencies
make test-unit         # backend unit tests — no external dependencies needed
make test-integration  # backend integration tests — needs a reachable Neo4j
make test-e2e           # full demo workflow — needs a reachable Neo4j
make test-frontend      # frontend unit/component tests
```

No `make`? Run Pytest/Vitest directly (with the backend venv activated
for the first three):
```powershell
cd backend; pytest tests/unit -q; pytest tests/integration -q; pytest tests/e2e -q; cd ..
cd frontend; npm run test; cd ..
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the reliability/observability
design (liveness vs. readiness, Neo4j circuit breaking, repository analysis
state, graceful degradation), [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
if something above doesn't work, and
[sample-repositories/demo-python-app/README.md](sample-repositories/demo-python-app/README.md)
for what the demo repository is designed to showcase.

## License

To be decided.

# Handover Checklist

A short, tick-through checklist for getting CodeGraph AI running and
demo-ready on a new machine. This is the fast path — for full detail on
any step, see [HANDOVER.md](HANDOVER.md), [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md),
and [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Commands below are given for
both a Unix-style shell (Git Bash/WSL/macOS/Linux) and plain Windows
PowerShell where they differ.

**Two port numbers you'll see repeatedly below:** this repo's
`docker-compose.yml` publishes Neo4j on **remapped host ports** — Bolt on
`7688` (not the Neo4j-standard 7687) and Browser on `7475` (not 7474) —
because the standard ports are already used by another local container on
some machines. Container-internal code (the Dockerized backend talking to
the Dockerized Neo4j) still uses the standard `7687`/`7474` on the Docker
network; anything running on your host (a host-run backend, or any
`python scripts/*.py` command) must use the published `7688` port instead.
Keep this straight — it is the single most common setup mistake with this
repo.

## 1. Required software

- **Git**
- **Docker Desktop** (or Docker Engine + Compose plugin) — runs Neo4j,
  and optionally the backend/frontend too
- **Python 3.12** exactly (`>=3.12,<3.13` — see `backend/pyproject.toml`)
  — only if you want to run the backend or any `scripts/*.py` file
  outside Docker
- **Node.js 20+** — only if you want to run the frontend outside Docker
- **[LM Studio](https://lmstudio.ai/)** — only if you want the zero-cost
  local LLM path (see step 4)
- **A POSIX shell, or Make, to use the `make ...` shortcuts shown below**
  — Git Bash, WSL, or Make-for-Windows. Plain Windows PowerShell/cmd.exe
  has no `make`; every `make` command below has a plain
  PowerShell-compatible alternative given right next to it, so Make is
  never strictly required.

### Host-script dependency (read this before step 6, 8, 9, or 10)

Every `python scripts/*.py` command in this checklist (`check_environment.py`,
`seed_demo_repository.py`, `run_demo_checks.py`, ...) and the backend
itself import the backend application's own code — they are **not**
standalone scripts. Running any of them, or the backend, directly on your
host (outside Docker) requires the backend's Python dependencies to
already be installed into your active Python environment. If you plan to
run only `docker compose up -d` and never a bare `python scripts/...`
command on your host, you can skip this — the backend container already
has its dependencies baked in.

**Beginner-safe Windows PowerShell setup**, from the project root:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ..
```

(If `.\.venv\Scripts\Activate.ps1` is blocked, PowerShell's script
execution policy is restrictive — run PowerShell as yourself, not admin,
and `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for just
that window, then retry.)

Unix equivalent (`make setup-backend` does exactly this):

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..
```

With that virtual environment **activated**, every `python scripts/...`
command below (and `make run-backend`, which is just `uvicorn` under that
same venv) will work from the project root in a new shell, as long as you
re-activate it first (`.\backend\.venv\Scripts\Activate.ps1` on
PowerShell, `source backend/.venv/bin/activate` on Unix).

## 2. First-time setup

```bash
git clone <this-repository-url>
cd codegraph-ai
```

## 3. Copy `.env.example` to `.env`

```bash
cp .env.example .env
```
```powershell
# PowerShell equivalent
Copy-Item .env.example .env
```

Every variable is documented inline in `.env.example`, including the
Neo4j port note from the top of this document. You do not need to change
anything except the LLM section (next step) to get a working demo.

## 4. Choose one LLM path

CodeGraph AI's ingestion, knowledge graph, vector search, and
**deterministic impact analysis all work with zero API keys** — only the
Assistant chat Q&A and LLM-written impact summaries need an LLM
configured. Pick exactly one path:

### Option A — LM Studio (zero-cost, fully local, recommended for a demo)

1. Install [LM Studio](https://lmstudio.ai/), download a chat/instruction
   model, load it, and start its Local Server (default port 1234) — full
   steps in [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md).
2. In `.env`:
   ```env
   LLM_PROVIDER=lmstudio
   LLM_MODEL=<the model id LM Studio is serving>
   LLM_API_KEY=lm-studio
   # Base URL depends on where the BACKEND runs (see LOCAL_LLM_SETUP.md
   # "Docker vs local base URL") — pick one:
   LLM_BASE_URL=http://host.docker.internal:1234/v1   # backend in Docker (already the default)
   # LLM_BASE_URL=http://localhost:1234/v1            # backend run directly on your host instead
   ```
3. No real API key needed. No cost. Works offline once the model is downloaded.

### Option B — Anthropic (cloud, paid)

In `.env`:
```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-5
LLM_API_KEY=<your real API key>
```
Requires a real, billable Anthropic API key. Never commit this file.

### Option C — No LLM at all (`make demo-check` only)

Leave `.env` as copied from `.env.example` (`LLM_API_KEY=changeme`). This
is a valid choice if you only want to **prove the pipeline works**, not
run live Q&A — see step 10. The Assistant chat page will show a clear
"could not generate an answer" message instead of an answer until you
pick Option A, B, or D.

### Option D — DeepSeek or another OpenAI-compatible cloud API (cheap cloud demo path)

The backend's `openai_compatible` provider isn't LM-Studio-specific — it
works with any OpenAI-compatible chat API, including cloud ones. This is
used **only for LLM answer generation and impact summaries** — embeddings
stay on the local `sentence_transformers` provider no matter which LLM
you pick. In `.env`:
```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_API_KEY=<your real DeepSeek API key>
```
Still a real, billable key (just typically far cheaper than Anthropic) —
never commit it. See `.env.example`'s "DEEPSEEK" section for the full
note. For OpenAI-compatible providers, the readiness check may call
`/models` if the provider exposes it, to confirm `LLM_MODEL` is actually
being served — provider behavior here can vary, so treat
`python scripts/check_llm.py` or the app's own readiness output as the
final verification, not a guarantee that `/models` works identically
everywhere.

## 5. Start Neo4j

```bash
docker compose up -d neo4j
docker compose ps        # wait until neo4j is "healthy" (~20-30s on first start)
```
(Identical in PowerShell — these are plain `docker` CLI commands, not `make`.)

Once healthy, Neo4j Browser is reachable at **http://localhost:7475**
(not 7474 — see the port note at the top of this document) with the
`NEO4J_USERNAME`/`NEO4J_PASSWORD` from your `.env`.

## 6. Start the backend

Via Docker (recommended — needs nothing from step 1's "Host-script
dependency" note):
```bash
docker compose up -d backend
```

Or locally on your host (faster iteration; needs the venv from step 1's
"Host-script dependency" note, and `NEO4J_URI=bolt://localhost:7688` in
your `.env` — the published host port, not `7687`):

```bash
make setup-backend
make run-backend
```

No `make` available (plain PowerShell)? Run the underlying commands —
`make setup-backend` is the venv block from step 1; `make run-backend` is:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
cd ..
```

## 7. Start the frontend

Via Docker (already started by `docker compose up -d` above if you ran
the full stack):
```bash
docker compose up -d frontend
```
Or locally (`make setup-frontend && make run-frontend`, or directly —
Node/npm commands work identically in PowerShell, no `make` needed):
```bash
cd frontend
npm install
npm run dev
```

## 8. Run the environment check

```bash
python scripts/check_environment.py
```
Needs the venv/dependencies from step 1's "Host-script dependency" note
activated first if you're not running this from inside the backend
container. This checks SQLite, workspace directories, Neo4j, Chroma, the
embedding model, and the LLM in one command, and tells you plainly what's
missing. If you chose Option C above, the LLM line will correctly report
as not configured — that's expected, not a failure.

## 9. Seed/index the demo repository

```bash
make demo-seed
```
No `make`? Run the script it calls directly (same venv requirement as
step 8):
```powershell
python scripts/seed_demo_repository.py
```
Imports and fully analyzes the included sample repository
(`sample-repositories/demo-python-app`) — parsing, graph construction,
and vector indexing. This step does **not** need an LLM. Note the
`repository_id` it prints; you'll want it for step 12.

## 10. Run `demo-check`

```bash
make demo-check
```
No `make`? Run the script it calls directly:
```powershell
python scripts/run_demo_checks.py
```
Exercises retrieval, citation validation, and impact analysis end-to-end
using a **built-in fake LLM** — see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#demo-check-and-the-fake-llm). It
needs no real API key and works even with `LLM_API_KEY=changeme`. A
`PASS` here proves the whole non-LLM pipeline (the hard part) is sound,
regardless of which LLM option you picked in step 4.

## 11. Open the frontend

http://localhost:5173

## 12. Ask demo questions

Only meaningful if you configured a real LLM (Option A, B, or D). In the UI:
Dashboard → the seeded repository → Assistant, then ask e.g.:
- "Where is authentication implemented?"
- "What does `AuthService.login` call?"

Or via the API — the real external path is `/api/v1/...`, always include
it in full:
```bash
curl -X POST http://localhost:8000/api/v1/repositories/<repository_id>/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Where is authentication implemented?"}'
```

On Windows PowerShell, use `curl.exe` (plain `curl` is a PowerShell alias
for `Invoke-WebRequest` with incompatible syntax):
```powershell
curl.exe -X POST http://localhost:8000/api/v1/repositories/<repository_id>/query `
  -H "Content-Type: application/json" `
  -d '{"question":"Where is authentication implemented?"}'
```

## 13. Run impact analysis

In the UI: open the repository → Impact Analysis → pick a function (e.g.
`AuthService.login`) → Analyze. This is deterministic graph traversal and
works regardless of your LLM choice (Option A/B/C) — only the
natural-language summary on top needs a real LLM.

## 14. Run tests

```bash
make test-unit          # no external dependencies needed
make test-integration   # needs a reachable Neo4j
make test-e2e            # needs a reachable Neo4j
make test-frontend       # frontend unit/component tests
```
No `make`? Run Pytest/Vitest directly (same venv requirement as step 8
for the backend ones):
```powershell
cd backend
pytest tests/unit -q
pytest tests/integration -q
pytest tests/e2e -q
cd ..\frontend
npm run test
```
None of the test suites call a real LLM or embedding API — they use fake
providers (see `backend/tests/fakes.py`).

## 15. Common errors and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| Assistant says "could not generate a reliable answer" | No real LLM configured (still Option C / `changeme`), or LM Studio not running | Pick Option A, B, or D in step 4; see [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md) |
| `GET http://localhost:8000/api/v1/health/ready` shows `neo4j: UNAVAILABLE` | Neo4j container not up yet, or `NEO4J_URI` uses the wrong port (`7687` instead of the published `7688` for a host-run backend) | `docker compose ps`; wait ~30s on first start; see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#neo4j-unavailable) |
| `check_embeddings.py` (or any `scripts/*.py`) fails with `ModuleNotFoundError` | Backend dependencies not installed in the active Python environment | Do the venv setup in step 1's "Host-script dependency" note |
| `check_embeddings.py` fails while downloading the model | The embedding model (~90MB) is downloading over a slow/blocked connection | Re-run it — downloads resume; see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#embedding-download-failure) |
| CORS error in the browser console | `CORS_ALLOWED_ORIGINS` doesn't match the frontend's actual origin | Check it matches `http://localhost:5173` (default) |
| `docker compose up` fails to bind a port | Something else already uses 8000/5173/7475/7688 on your machine | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#port-conflict) — this repo already remaps Neo4j to 7475/7688 for exactly this reason |
| Docker commands fail with a connection/pipe error | Docker Desktop isn't running | Start Docker Desktop and wait for "running" before retrying |
| `'make' is not recognized` in PowerShell | No Make installed, and no Git Bash/WSL shell in use | Use the PowerShell-equivalent command given next to each `make` step above, or install Git Bash/WSL/Make |
| `curl` in PowerShell gives unexpected parameter errors | Plain `curl` is aliased to `Invoke-WebRequest` in PowerShell, not real curl | Use `curl.exe` instead of `curl` |

## 16. Final "ready to demo" checklist

- [ ] `python scripts/check_environment.py` passes (or clearly shows only
      the LLM line as not-configured if you deliberately chose Option C)
- [ ] `make demo-seed` (or `python scripts/seed_demo_repository.py`)
      completed and printed a `repository_id`
- [ ] `make demo-check` (or `python scripts/run_demo_checks.py`) reports
      `PASS` for every check
- [ ] Frontend loads at http://localhost:5173 and shows the seeded repository
- [ ] If demoing live Q&A: one real question through the Assistant UI
      returns an answer with citations (Option A, B, or D configured)
- [ ] Impact Analysis page renders a result for at least one function

## 17. What not to touch before the demo

- Don't edit `.env` mid-demo — the backend reads it once at process
  start; changing it requires a restart (`docker compose restart backend`).
- Don't run `docker compose down -v` — the `-v` flag deletes all data
  (Neo4j graph, Chroma vectors, SQLite), including your seeded demo repo.
- Don't switch `EMBEDDING_MODEL_NAME` right before a demo — it changes
  the vector space and requires re-indexing every repository (see
  [HANDOVER.md](HANDOVER.md#changing-the-embedding-model)).
- Don't commit or share your real `.env` — it may contain a real API key.
- Don't delete `sample-repositories/demo-python-app` — it's the
  hand-built fixture the whole demo walkthrough depends on.
- Don't "correct" the Neo4j ports back to 7474/7687 — 7475/7688 are this
  repo's deliberate published-host-port remap, not a mistake.

## 18. Before GitLab push checklist

Run through this once, right before pushing this repository to GitLab
(or any remote) for the first time, or before handing it to someone else
who will push it:

- [ ] `.env` is **not** present in what you're about to add/commit — only
      `.env.example` should be tracked (check `.gitignore` covers `.env`
      and `.env.*` except `!.env.example` — it already does).
- [ ] No real API key, password, or token appears anywhere in a tracked
      file — grep for anything that doesn't look like `changeme`,
      `lm-studio`, or an angle-bracket placeholder before pushing:
      `grep -rn "sk-\|api[_-]key" --include=*.md --include=*.py --include=*.ts .`
      (adjust the pattern for your key's actual prefix).
- [ ] No root-level `*.log`, `*.tmp`, or other local run artifacts are
      staged (`.gitignore` already excludes `*.log`/`logs/` — confirm
      `git status` doesn't show one anyway, e.g. from before `.gitignore`
      was in place).
- [ ] Local generated/private folders are not staged — all of these are
      per-machine state, not source, and `.gitignore` now explicitly
      excludes every one of them:
      - `data/` and `backend/data/` (SQLite db, Chroma vectors, ingested
        repos/workspaces)
      - `backend/tests/.test-data/` (test scratch data)
      - `.claude/` (local Claude Code settings — per-machine, not shared
        project config)
      - `node_modules/` (frontend) and `backend/.venv/`
      - `frontend/dist/` (built frontend output)
      - `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`
      - Local model weight/cache files (`*.gguf`, `*.safetensors`,
        `*.pt`, `*.pth`, `*.onnx`) — large, regenerable downloads, never
        source
      If any of these show up in `git status` anyway, it means they were
      already tracked from before `.gitignore` covered them — `git rm
      -r --cached <path>` to untrack without deleting the local copy.
- [ ] `make test-unit` (or `pytest tests/unit -q`) passes — doesn't need
      Neo4j or any LLM.
- [ ] `make demo-check` (or `python scripts/run_demo_checks.py`) passes —
      proves the core pipeline still works post-change, with no API key
      needed.
- [ ] Skim `git diff`/`git status` (once this becomes a real git repo) one
      more time for anything that looks like a stray personal path,
      machine-specific absolute path, or credential before the final push.

## 19. Before public hosting (security) checklist

This repo is a **local/dev tool, not ready for public or multi-tenant
hosting**. Do not skip straight here without reading
[SECURITY.md](../SECURITY.md) — this is a short pointer, not a
replacement for it. Full checklist:
[HANDOVER.md "Before public hosting — security checklist"](HANDOVER.md#before-public-hosting--security-checklist).
In short, before exposing this beyond your own machine/trusted network
you need, at minimum: real authentication in front of the API, non-
placeholder `NEO4J_PASSWORD`/`LLM_API_KEY`, a non-wildcard
`CORS_ALLOWED_ORIGINS`, TLS termination in front of the stack, and
ingestion limits re-checked for a multi-user load. None of that exists
today — treat "ready for GitLab push" and "ready for friend to run
locally" as entirely separate from "ready to host publicly."

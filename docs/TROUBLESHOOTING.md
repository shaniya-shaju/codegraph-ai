# Troubleshooting

Quick fixes for the problems most likely to come up when setting up or
running CodeGraph AI. For LM Studio specifically, see
[LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md)'s own "Common errors" table
first. For the general first-time setup path, see
[HANDOVER.md](HANDOVER.md); for a condensed env-variable reference, see
[ENVIRONMENT.md](ENVIRONMENT.md); for a ready-to-run demo script, see
[DEMO.md](DEMO.md).

Start with the environment check — it diagnoses most of what's below in
one command:

```bash
python scripts/check_environment.py
```

**Windows note:** this doc's `make ...` commands assume a POSIX shell.
From plain PowerShell/cmd.exe (no Git Bash, WSL, or Make installed), run
the underlying `python scripts/*.py` command shown next to each `make`
target instead — see [HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) for
the full mapping and Windows setup steps. Also use `curl.exe` rather than
plain `curl` in PowerShell (`curl` there is an `Invoke-WebRequest` alias
with different syntax/output).

## Neo4j unavailable

**Symptoms:** `GET /api/v1/health/ready` shows `neo4j: UNAVAILABLE`; the
Graph page, Impact Analysis page, and graph-mode retrieval show a
"Knowledge graph unavailable" message; `python scripts/check_neo4j.py`
fails.

- Confirm the container is actually running and healthy:
  ```bash
  docker compose ps
  docker compose up -d neo4j
  ```
- If it's newly started, give it 20-30 seconds — the container's own
  healthcheck (`neo4j` service in `docker-compose.yml`) has a 30s
  `start_period`.
- Confirm `NEO4J_URI`/`NEO4J_USERNAME`/`NEO4J_PASSWORD` in your `.env`
  match what the container was started with (`NEO4J_AUTH`) — if you
  change `NEO4J_PASSWORD` after the Neo4j volume already has data, the
  *old* password remains in effect until you either reset the volume
  (`docker compose down -v`, which deletes graph data) or change it via
  `cypher-shell`/Neo4j Browser instead.
- Running the backend outside Docker (host-run, against Neo4j started by
  this repo's `docker compose up -d neo4j`)? `NEO4J_URI` must be
  `bolt://localhost:7688` — the **published host port**, not the
  container-internal `7687` — this repo's `docker-compose.yml` remaps
  Neo4j's Bolt port to 7688 on the host (see "Port conflict" below).
  `bolt://neo4j:7687` (container-internal hostname/port) only resolves
  inside the Docker Compose network, for the containerized backend — see
  [HANDOVER.md](HANDOVER.md)'s "Local backend vs Docker backend" table.
- The backend fails fast on a Neo4j outage (a few seconds, not the
  driver's ~30-55s default) and opens a circuit breaker after repeated
  failures — see `NEO4J_OPERATION_TIMEOUT_SECONDS`/`NEO4J_CIRCUIT_*` in
  `.env.example` if you need to tune this for a slow/remote Neo4j.
- Once Neo4j is reachable again, `docker compose up -d backend` isn't
  needed — the backend reconnects automatically on the next request (the
  circuit breaker's cooldown, or immediately if it wasn't open).

## LLM unavailable

**Symptoms:** `GET /api/v1/health/ready` shows `llm: UNAVAILABLE` or
`NOT_LOADED`; the Assistant page shows "I could not generate a reliable
answer right now — the language model request failed"; `python
scripts/check_llm.py` fails.

See [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md) for the local (LM Studio)
path in full. Quick checklist:

- `LLM_PROVIDER=lmstudio` (or `openai_compatible`) but `LLM_BASE_URL` is
  unset → readiness reports `not_configured`. Set it — see
  LOCAL_LLM_SETUP.md's "Docker vs local base URL".
- `LLM_PROVIDER=anthropic` but `LLM_API_KEY` is still the placeholder
  `changeme` → also `not_configured`. Set a real key, or switch to
  `lmstudio` instead.
- A cloud (`anthropic`) key that looks configured but is actually invalid
  only surfaces as a failure at generation time (readiness never makes a
  live paid API call to check it) — `check_llm.py`'s real generation
  attempt will show the actual error (e.g. `401 invalid x-api-key`).

**What `LLM_API_KEY=changeme` actually means:** this is the untouched
placeholder from `.env.example` — it means no real LLM is configured yet,
not a bug. With it in place: the Assistant chat page and LLM-written
impact summaries will abstain with a clear message instead of answering,
but **ingestion, knowledge-graph construction, vector indexing, symbol
search, and deterministic impact analysis all still work normally** —
none of them call the LLM. See the "demo-check and the fake LLM" section
below for how to verify the whole pipeline without ever setting a real
key, or [docs/HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) for the three
supported paths (LM Studio / Anthropic / no-key).

## demo-check and the fake LLM

**Symptoms:** none — this section explains expected, by-design behavior
of `make demo-check` so it isn't mistaken for a bug.

`make demo-check` (`scripts/run_demo_checks.py`) runs retrieval, citation
validation, and impact analysis against the seeded demo repository using
a built-in `_SmartFakeLLMProvider` defined in that script — **not** your
configured `LLM_PROVIDER`. It inspects the real evidence pool retrieval
produced and cites whatever is actually there, exercising the real
citation-validation pipeline end-to-end without any network call or API
key. This is why `demo-check` reports `PASS` even when `LLM_API_KEY` is
still `changeme`.

This fake is local to that one script — it is not a `.env` toggle and
does not affect the Assistant UI, `/query` endpoint, or any other part of
the running application, all of which always use the real provider
configured by `LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY`. To verify your
*real* configured LLM instead, ask a question through the Assistant UI or
run `python scripts/check_llm.py`.

## Wrong model name

**Symptoms:** readiness reports `llm: UNAVAILABLE` with
`detail: "configured_model_not_served"`.

Only applies to `LLM_PROVIDER=lmstudio`/`openai_compatible`. For these
providers, the readiness check may call `GET {LLM_BASE_URL}/models` if
the provider exposes that endpoint, to confirm `LLM_MODEL` is actually
being served. Provider behavior here can vary — not every
OpenAI-compatible server implements `/models` identically — so treat
`python scripts/check_llm.py` (a real generation call) or the app's own
`GET /api/v1/health/ready` output as the final verification, not this
detail string alone. `LLM_MODEL` must exactly match a served model id —
see LOCAL_LLM_SETUP.md step 5 for how to find it for LM Studio
specifically (`curl http://localhost:1234/v1/models` — on Windows
PowerShell use `curl.exe http://localhost:1234/v1/models` instead —
against your running LM Studio server); for a cloud `openai_compatible`
provider like DeepSeek, check that provider's own API documentation for
the equivalent.

## Embedding download failure

**Symptoms:** `python scripts/check_embeddings.py` fails while loading
the model; the first repository analysis after a fresh setup fails at the
vector-indexing stage.

- The default embedding model (`sentence-transformers/all-MiniLM-L6-v2`)
  is a real download (~90MB) from the Hugging Face Hub on first use — a
  slow or interrupted connection can fail partway through. Re-run
  `python scripts/check_embeddings.py`; Hugging Face's client resumes/
  retries partial downloads on its own in most cases.
- If you're behind a proxy or in a network that blocks
  `huggingface.co`, configure `HF_ENDPOINT`/`HTTPS_PROXY` per Hugging
  Face's own documentation.
- Downloaded weights are cached under the standard Hugging Face cache
  directory (`~/.cache/huggingface` on the host, or inside the
  `backend_data` volume's container filesystem when run via Docker) —
  they are **not** re-downloaded on every restart.

## `trust_remote_code` problem

Only relevant if you've switched `EMBEDDING_MODEL_NAME` away from the
default to a model that ships custom modeling code on the Hub (e.g.
`jinaai/jina-embeddings-v2-base-code`) — the default
(`sentence-transformers/all-MiniLM-L6-v2`) never hits this.

**Symptoms:** loading the model fails with an error mentioning
`trust_remote_code`, or (a subtler problem) it loads *without* error but
logs warnings like `Some weights of BertModel were not initialized from
the model checkpoint ... and are newly initialized`.

- Such a model ships custom modeling code on the Hub. CodeGraph AI never
  enables `trust_remote_code` silently — see `EMBEDDING_TRUST_REMOTE_CODE`
  in `.env.example` and SECURITY.md.
- **Important, session-observed nuance:** depending on your installed
  `transformers` version, leaving `EMBEDDING_TRUST_REMOTE_CODE=false`
  does not always fail loudly for a model like this — it can silently
  fall back to loading it as a generic `BertModel`, which logs a
  "weights ... newly initialized" warning and means some layers are
  **randomly initialized rather than loaded from the real pretrained
  checkpoint**. The model will still produce embeddings of the right
  shape (so a shallow check can look like it "works"), but retrieval
  quality will be degraded in a way that isn't obvious from the
  application alone. If you see that warning in the backend logs:
  - Set `EMBEDDING_TRUST_REMOTE_CODE=true` to load the model's real,
    intended code path (this does execute code shipped by the model
    author on the Hub — only do this for a model source you trust; see
    SECURITY.md), **or**
  - Switch back to the default
    (`EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2`),
    which needs no custom code at all.
  - Either way, re-run `python scripts/check_embeddings.py` and confirm
    the warning is gone after changing the setting.

## "Clone a repository from a URL" errors

**Symptoms:** pasting a GitHub/GitLab URL into **Import Repository →
Clone Git Repository** (or `POST /api/v1/repositories/clone`) fails
immediately, before any clone progress happens.

- **`GIT_CLONING_DISABLED` (403)** — `REPO_URL_CLONE_ENABLED=false` in
  `.env`. The whole URL-clone feature is turned off on this server; ZIP
  upload and local-path ingestion still work. Set it to `true` and
  restart the backend if you want this feature available.
- **`GIT_HOST_NOT_ALLOWED` (400)** — the URL's host isn't in
  `REPO_CLONE_ALLOWED_HOSTS` (default `github.com,gitlab.com`). Only
  those two hosts are supported out of the box; this is deliberate (see
  [SECURITY.md](../SECURITY.md) "Repository acquisition safety") — widen
  the list only if you understand the SSRF-adjacent risk of letting this
  server fetch from arbitrary hosts.
- **`INVALID_GIT_URL` (400)** — the URL itself is structurally rejected:
  not HTTPS, has embedded credentials (`https://user:pass@...`), is an
  SSH or scp-style URL (`ssh://...`, `git@host:path`), a local path, or
  points at a loopback/private-network address. **Private repositories
  and SSH authentication are not supported** — there's no credential
  input anywhere in this flow, by design.
- **`GIT_CLONE_FAILED` (422)** — the URL passed every check above but the
  actual `git clone` failed: wrong repo name/typo, repository is private
  (404 from the host), branch doesn't exist, or it exceeded
  `INGESTION_CLONE_TIMEOUT_SECONDS` / `INGESTION_MAX_REPO_SIZE_MB`. The
  error message includes git's own last stderr line — check that first.

See `.env.example`'s "Remote repository URL cloning" section for every
related setting, and [API_SPEC.md](../API_SPEC.md)'s `POST
/api/v1/repositories/clone` entry for the full contract.

**Not for public/shared deployment:** this endpoint has no
authentication or rate limiting (same as everything else in this v1 —
see SECURITY.md). The host allow-list reduces but does not eliminate the
risk of an unauthenticated caller repeatedly triggering outbound clones
from your server. Keep `REPO_URL_CLONE_ENABLED=false` (or don't expose
the backend publicly at all) outside a trusted local/internal setting.

## CORS

**Symptoms:** the frontend's requests fail in the browser console with a
CORS error; the backend itself responds fine via `curl`.

- `CORS_ALLOWED_ORIGINS` in `.env` must include the exact origin the
  frontend is served from (scheme + host + port) — the default
  `http://localhost:5173` matches `npm run dev`'s default Vite port and
  the Docker Compose frontend service's published port.
- Never set this to `*` — the backend sends `allow_credentials: true`,
  and browsers reject a wildcard origin combined with credentials
  outright (see SECURITY.md).
- Changed the port either side? Update both: `CORS_ALLOWED_ORIGINS` on
  the backend and `VITE_API_BASE_URL` in `frontend/.env` (or the
  `VITE_API_BASE_URL` Docker Compose variable) on the frontend.

## Docker daemon not running

**Symptoms:** `docker compose up` / `docker compose ps` fail with a
connection error to the Docker engine (e.g. a named pipe/socket not
found), even though `docker compose config` succeeds (that command only
parses the compose file — it doesn't need a running daemon).

- Start Docker Desktop (or your Docker Engine) and wait for it to report
  "running" before retrying.
- On Windows, this specifically looks like a `dockerDesktopLinuxEngine`
  pipe error — Docker Desktop needs to be manually started; the CLI being
  installed doesn't mean the daemon is up.

## Port conflict

**Symptoms:** `docker compose up` fails to bind a port, or `make
run-backend`/`run-frontend` fails to start.

Default **published host** ports in this repo: backend `8000`, frontend
`5173`, Neo4j `7475` (Browser) and `7688` (Bolt), LM Studio `1234` (not
managed by this project). Neo4j's *container-internal* ports are always
the Neo4j-standard `7474`/`7687` — this repo's `docker-compose.yml`
deliberately remaps them to `7475`/`7688` on the host, specifically
because `7474`/`7687` are already used by another local container on some
machines. `NEO4J_URI=bolt://localhost:7688` (host-run backend/scripts) and
`http://localhost:7475` (Neo4j Browser in your browser) already account
for this remap — don't "fix" them back to 7474/7687 thinking that's the
real default.

If something else on your machine already uses one of the ports above:

- Backend: set `APP_PORT` in `.env` (Docker Compose reads it for the
  published port too).
- Frontend: change the port in `frontend/vite.config.ts` or pass
  `npm run dev -- --port <port>`; update `CORS_ALLOWED_ORIGINS`
  accordingly.
- Neo4j: change the left-hand side (host side) of the port mappings in
  `docker-compose.yml`'s `neo4j` service (`"7475:7474"` / `"7688:7687"` —
  leave the right-hand, container-internal side unchanged) — and update
  `NEO4J_URI` in `.env` to match whatever new host port you picked.

## Chroma persistence

**Symptoms:** semantic search/citations disappear after a restart; a
repository's vector status looks `READY` but retrieval returns nothing.

- ChromaDB runs embedded (a local persistent directory, not a separate
  service) — `CHROMA_PERSIST_DIRECTORY` (host: `./data/chroma`, Docker:
  the `backend_data` volume's `/data/chroma`). As long as that
  directory/volume isn't deleted, indexed data survives restarts.
- `docker compose down -v` deletes named volumes (`backend_data`,
  `neo4j_data`, ...) — use plain `docker compose down` (no `-v`) to stop
  the stack without losing data.
- If a collection looks present but empty/stale, re-run analysis for
  that repository (see "stale repository index" below) rather than
  editing the Chroma directory directly.

## Stale repository index

**Symptoms:** the dashboard shows a repository's overall status as
`STALE`; answers reference code that no longer matches the repository.

This is expected, detected behavior, not a bug — CodeGraph AI compares
the repository's current content revision against the one it last
indexed (see `ARCHITECTURE.md`'s staleness detection). Re-analyze it:

- From the UI: open the repository, click **Reanalyze**.
- From the API: `POST /api/v1/repositories/{repository_id}/analyze` with
  `{"force": true}`.
- From the CLI, for the seeded demo repository specifically:
  `make demo-reset && make demo-seed` re-imports it from scratch (no
  `make`? run `python scripts/reset_demo.py` then
  `python scripts/seed_demo_repository.py`).

# Environment Variables — Quick Reference

A condensed, at-a-glance companion to [.env.example](../.env.example),
which remains the source of truth (every variable there has a fuller
comment, its default, and whether it's required). Use this page to find
the right variable fast; use `.env.example` for the full explanation.

## The two things nearly everyone changes

| Variable | Why you'd change it |
|---|---|
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` | Which LLM answers questions and writes impact summaries — see "LLM" below |
| `NEO4J_URI` | Only if running the backend on your host instead of in Docker — see "The Neo4j port trap" below |

Everything else works at its committed default for a local demo.

## The Neo4j port trap

This repo's `docker-compose.yml` publishes Neo4j on **remapped host
ports** — not the Neo4j-standard ones — because 7474/7687 are already
used by another local container on some machines:

| | Container-internal (standard) | Published host port (this repo) |
|---|---|---|
| Bolt | `7687` | **`7688`** |
| Browser (HTTP) | `7474` | **`7475`** |

| Who connects | `NEO4J_URI` to use |
|---|---|
| Backend running **inside Docker Compose** | `bolt://neo4j:7687` (already set by `docker-compose.yml` — don't change it) |
| Backend/scripts running **on your host** (`make run-backend`, any `python scripts/*.py`) | `bolt://localhost:7688` |

Getting this backwards is the single most common setup mistake with this
repo — see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#neo4j-unavailable) and
[HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) for more.

## LLM — four supported paths

| `LLM_PROVIDER` | What it is | Cost | Needs |
|---|---|---|---|
| `anthropic` | Cloud, Anthropic's own API | Paid | Real `LLM_API_KEY` |
| `lmstudio` (alias of `openai_compatible`) | Local, via [LM Studio](LOCAL_LLM_SETUP.md) | Free | `LLM_BASE_URL`, `LLM_MODEL` matching what LM Studio serves |
| `openai_compatible` pointed at a cloud endpoint (e.g. DeepSeek) | Cloud, any OpenAI-compatible API | Usually cheaper than Anthropic | Real `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` — see `.env.example`'s "DEEPSEEK" section |
| *(left as `changeme`)* | No LLM at all | Free | Nothing — `make demo-check` / `python scripts/run_demo_checks.py` still passes via a built-in fake LLM; the Assistant chat page abstains |

`lmstudio` and `openai_compatible` are the same code path (see
`backend/app/rag/llm_provider.py`) — `lmstudio` is just a friendlier name
for the common local case. This is never a separate "fake" or "demo"
mode toggle — the fake LLM used by `demo-check` is internal to that one
script only, and never affects the running application (see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#demo-check-and-the-fake-llm)).

Whichever `LLM_PROVIDER` you pick is used **only for answer generation
and impact summaries** — it never affects embeddings/retrieval, which
always run on the local `sentence_transformers` provider below. For
`openai_compatible` providers specifically, the app's readiness check may
query `{LLM_BASE_URL}/models` if the provider exposes it, but not every
provider implements that endpoint the same way — `python
scripts/check_llm.py` or the live readiness output is the authoritative
check, not an assumption that `/models` exists.

## Embeddings — always local, no key needed

`EMBEDDING_PROVIDER=sentence_transformers` runs on your machine — no API
key, no per-request network call (one-time model download from Hugging
Face on first use). `EMBEDDING_API_KEY` is a reserved-for-later field the
current provider never reads. See `.env.example`'s EMBEDDINGS section and
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#trust_remote_code-problem) if you
switch away from the default model.

## Cloning a repository from a URL — security-sensitive, read before changing

`POST /api/v1/repositories/clone` ("paste a GitHub/GitLab URL") is
public-HTTPS-only, never supports private repos or SSH, and is further
restricted by three settings:

| Variable | Default | What it does |
|---|---|---|
| `REPO_URL_CLONE_ENABLED` | `true` | Kill switch — `false` disables the feature entirely (ZIP/local-path unaffected) |
| `REPO_CLONE_ALLOWED_HOSTS` | `github.com,gitlab.com` | Exact, case-insensitive host allow-list — widening it widens this server's SSRF-adjacent surface |
| `REPO_CLONE_DEPTH` | `1` | Shallow-clone depth; 1 is enough for parsing/indexing |

**Docker Compose users:** these three are passed through to the
`backend` service in `docker-compose.yml` the same way the other
`INGESTION_*` settings are — edit them in your root `.env` as normal, no
separate Docker-specific configuration needed.

**This endpoint has no authentication or rate limiting** (true of this
whole v1 — see [SECURITY.md](../SECURITY.md)). The allow-list reduces,
but does not eliminate, the risk of an unauthenticated caller using your
server to make repeated outbound requests. Do not expose it on a
shared/public network without adding auth and rate limiting first — see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#clone-a-repository-from-a-url-errors)
for the specific errors this produces.

## Everything else

| Section | Covers | Change it if... |
|---|---|---|
| APPLICATION | Host/port, log level, CORS | You need a different port, or are about to host beyond localhost (see CORS note in [HANDOVER.md](HANDOVER.md#before-public-hosting--security-checklist)) |
| DATABASE | SQLite URL | You're migrating to PostgreSQL (schema is kept compatible, not required for local use) |
| WORKSPACE | Ingestion allow-list/scratch dirs, size/time caps | Rarely — defaults are sane for local use |
| CHROMA | Vector store persistence dir/collection prefix | Rarely |
| RETRIEVAL | Hybrid retrieval weights, evidence/citation bounds | Only if tuning retrieval quality — see ARCHITECTURE.md |
| IMPACT | Traversal depth/node caps, risk-score weights | Only if tuning impact analysis — these are explicitly untuned heuristics, never a probability of failure |

Full detail, defaults, and required/optional status for every one of
these: [.env.example](../.env.example).

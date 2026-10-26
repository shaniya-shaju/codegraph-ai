# Local LLM Setup (LM Studio)

CodeGraph AI's grounded-answer generation and impact-summary generation
need a chat/instruction-following LLM (see [ARCHITECTURE.md](../ARCHITECTURE.md)
and [AGENTS.md](../AGENTS.md) rule 2 — the LLM only explains and
summarizes evidence the graph/vector retrieval already found; it never
asserts a code relationship the graph doesn't contain). You can point
this at a cloud provider (Anthropic) or run a model entirely on your own
machine via [LM Studio](https://lmstudio.ai/). This document covers the
local path.

**This is not the embedding model.** CodeGraph AI uses *two* separate
models for two separate jobs — see `.env.example`'s EMBEDDINGS section:

| | LLM (this document) | Embedding model |
|---|---|---|
| Job | Turns retrieved evidence into a natural-language answer | Turns code into vectors so it can be *found* in the first place |
| Configured by | `LLM_*` variables | `EMBEDDING_*` variables |
| Local option | LM Studio | `sentence_transformers` (already local by default) |

Downloading and loading a chat model in LM Studio does **not** give you
an embedding model, and vice versa. Both need to be working for the
Assistant page to answer a question end-to-end (see
`GET /api/v1/health/ready`'s `embedding_provider` and `llm` fields).

## 1. Install LM Studio

Download and install LM Studio for your OS from https://lmstudio.ai/.
No account or API key is required for local use.

## 2. Download a model

Inside LM Studio, use the built-in model search/download UI (the
magnifying-glass icon) to pull a **chat/instruction** model — not a base
completion model, and not an embedding model. CodeGraph AI asks the model
to:

- Follow a structured system prompt reliably (cite evidence by `[E<n>]`
  marker, say when evidence is insufficient rather than guessing).
- Return valid structured/tool-call output for the non-streaming answer
  path (`with_structured_output`).

Any reasonably modern instruction-tuned chat model that LM Studio can
serve works — CodeGraph AI does not hardcode or require any specific
model id; see "Choosing a model by hardware" below for general guidance.
Larger models generally produce more coherent, more reliably-grounded
repository explanations, but need more RAM/VRAM and are slower per
answer — there's a real quality/resource trade-off, and the right choice
depends on your machine, not on anything CodeGraph AI enforces.

## 3. Load the model

In LM Studio's chat/model tab, load the model you downloaded. Only one
(or a few, depending on your LM Studio version and available memory)
model can be loaded and served at a time — whichever is loaded when you
start the local server (next step) is what CodeGraph AI will talk to.

## 4. Start the Local Server

In LM Studio, open the "Local Server" (sometimes labeled "Developer" or a
`</>` icon) tab and click **Start Server**. Note the port shown — it
defaults to **1234**, giving a base URL of `http://localhost:1234/v1`.
LM Studio's local server speaks the OpenAI chat-completions API, which is
exactly what CodeGraph AI's `openai_compatible`/`lmstudio` provider talks
to (see `backend/app/rag/llm_provider.py` — there is no
LM-Studio-specific client; it is treated as a normal OpenAI-compatible
endpoint).

## 5. Determine the served model id

CodeGraph AI's `LLM_MODEL` must exactly match the model identifier LM
Studio is currently serving — not a display name, a nickname, or a
filename. To find it:

- LM Studio's Local Server tab shows the loaded model's id directly, or
- Query it yourself once the server is running:
  ```bash
  curl http://localhost:1234/v1/models
  ```
  On Windows PowerShell, use `curl.exe http://localhost:1234/v1/models`
  instead (plain `curl` there is an `Invoke-WebRequest` alias with
  different syntax). Copy the `"id"` field from the response into
  `LLM_MODEL`.

If `LLM_MODEL` doesn't match anything currently served, CodeGraph AI's
readiness check (`GET /api/v1/health/ready`, `dependencies.llm`) reports
`UNAVAILABLE` with `detail: "configured_model_not_served"` rather than a
generic connection error — see step 7.

## 6. Configure CodeGraph AI

In your `.env` (see the root [.env.example](../.env.example)'s LLM /
LM STUDIO sections):

```env
LLM_PROVIDER=lmstudio
LLM_MODEL=<the exact id from step 5>
LLM_API_KEY=lm-studio
```

`LLM_PROVIDER=openai_compatible` works identically — `lmstudio` is just a
documented, friendlier alias for the same code path (see
`backend/app/rag/llm_provider.py`'s `normalize_llm_provider`). Any
non-empty `LLM_API_KEY` value works; LM Studio doesn't check it, but some
HTTP clients refuse to send a request with an empty `Authorization`
header, so leaving it blank can cause a confusing failure.

### Docker vs local base URL

`LLM_BASE_URL` depends on **where the CodeGraph AI backend process itself
is running** — LM Studio always runs on your host machine either way (it
is not, and cannot be, containerized — see §18 of the transferability
task and item 7 below).

| Backend is running... | `LLM_BASE_URL` |
|---|---|
| Directly on your host (`make run-backend`, no Docker) | `http://localhost:1234/v1` |
| Inside Docker Desktop (Mac/Windows), via `docker compose up` | `http://host.docker.internal:1234/v1` |
| Inside Docker on a Linux host | `http://host.docker.internal:1234/v1` — the provided `docker-compose.yml` already adds the Linux-only `extra_hosts: host.docker.internal:host-gateway` mapping for the backend service, so the same hostname resolves there too |

The default `LLM_BASE_URL` inside `docker-compose.yml` is already set to
`http://host.docker.internal:1234/v1` for exactly this reason — you
normally don't need to change it there, only in a local (non-Docker)
`.env`.

## 7. Test connectivity

```bash
python scripts/check_llm.py
```

This script imports the backend application directly, so it needs the
backend's Python dependencies installed in your active environment first
(see [HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) step 1's "Host-script
dependency" note and its Windows PowerShell venv walkthrough) — otherwise
it fails with `ModuleNotFoundError` before testing anything.

This instantiates the real configured provider, checks connectivity, and
performs one minimal real generation call — see the script's own output
for `PASS`/`FAIL` per step. It never prints your API key. You can also
check `GET /api/v1/health/ready` (`dependencies.llm`) at any time — it
reports `READY` / `UNAVAILABLE` / a "not configured" state without ever
generating text (see `backend/app/core/dependencies/status_service.py`'s
`check_llm`).

## 8. Common errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `check_llm.py` / readiness reports connection refused | LM Studio's Local Server isn't started, or the port doesn't match `LLM_BASE_URL` | Start the server in LM Studio; confirm the port |
| readiness reports `detail: "configured_model_not_served"` | `LLM_MODEL` doesn't match what LM Studio is currently serving | Re-check step 5; the model may have been unloaded/swapped since you set `LLM_MODEL` |
| Backend runs in Docker but can't reach LM Studio, while the same config works when run locally | Wrong `LLM_BASE_URL` for a containerized backend | Use `http://host.docker.internal:1234/v1`, not `http://localhost:1234/v1` — see the table above |
| Answers always abstain / assistant says "the language model request failed" | Any of the above, or the model timed out (`LLM_TIMEOUT_SECONDS`) — answer generation degrades to a clear abstained answer rather than crashing, by design | Run `check_llm.py` for a specific reason; increase `LLM_TIMEOUT_SECONDS` for a slow local model |
| Structured output / citations look malformed | The loaded model is small/not well instruction-tuned and struggles to follow the structured prompt reliably | Try a larger or more instruction-tuned model — see below |

See also [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Choosing a model by hardware

CodeGraph AI does not require or hardcode any specific model — this is
general guidance, not a supported-models list. "RAM" below means total
system RAM if running the model on CPU, or VRAM if running on GPU;
LM Studio shows an estimated fit/speed indicator per model before you
download it, which is the most accurate guide for your specific machine.

- **8 GB RAM / low-resource machines**: stick to small (roughly 3B–4B
  parameter) quantized instruction models. Expect answers to be
  serviceable for straightforward questions but less reliable at
  strictly following the citation-marker format on complex, multi-file
  evidence — CodeGraph AI's grounding/citation validation (see
  [ARCHITECTURE.md](../ARCHITECTURE.md)) will still reject anything it
  can't verify, so incorrect citations get stripped rather than shown,
  but you may see more abstentions.
- **16 GB RAM**: comfortably runs quantized ~7B–8B models, generally a
  good balance of answer quality and response latency for this
  application.
- **32 GB RAM, or a GPU-capable machine**: can run larger (~13B+)
  quantized models, or run a mid-size model at higher precision/faster
  speed. Larger models are typically more reliable at following the
  structured grounding instructions on harder, multi-hop questions.

Whatever you choose, verify it end-to-end with `python scripts/check_llm.py`
and a real question through the Assistant page before relying on it.

# Demo Script

A concrete, ready-to-run demo walkthrough for CodeGraph AI, built around
the included sample repository
([sample-repositories/demo-python-app](../sample-repositories/demo-python-app)).
Do the setup in [HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) first (through
step 11 — frontend open) before following this script.

## What you're demoing

CodeGraph AI parses a Python repository into a knowledge graph (Neo4j) +
vector index (ChromaDB), then answers questions and computes change-impact
analysis grounded in that graph — never in the LLM's guesses (see
[AGENTS.md](../AGENTS.md) rule 2). The demo repository is small and
hand-built specifically to make this provable in a few minutes:

```
POST /login  -> login_endpoint -> AuthService.login
                                     -> UserRepository.find_by_email
                                     -> TokenService.create_access_token

POST /users  -> create_user_endpoint (async) -> UserService.create_user
                                                   -> UserRepository.save
```

- `UserRepository` **extends** `BaseRepository` (inheritance edge).
- `AuthService.login` has a direct caller (`login_endpoint`) *and*,
  transitively, is reachable from the public `POST /login` API endpoint —
  good for demoing impact analysis distinguishing direct vs. transitive
  dependents and API exposure.
- `app.models.user.format_user_display_name` is an intentionally
  **isolated** utility — never called anywhere else in the repo. Good for
  demoing "nothing depends on this" as a real, useful answer.
- `app.security.tokens.validate_credentials` and
  `app.services.user_service.validate_credentials` intentionally **share
  a name** across two different modules — good for demoing
  symbol-ambiguity handling (both should surface as candidates, not a
  guess).
- `tests/test_auth.py` / `tests/test_users.py` call production code
  directly — good for demoing the "related tests" signal.

See the demo repository's own
[README.md](../sample-repositories/demo-python-app/README.md) for more.

## Before you start

Which parts of this script work depends on your LLM choice (see
[HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) step 4):

- **Option A (LM Studio) / B (Anthropic) / D (DeepSeek)** — every step
  below works, including live chat answers.
- **Option C (no LLM)** — skip the "Assistant chat" steps' live answers;
  everything else (Graph explorer, Impact Analysis, `demo-check`) still
  works and is still worth showing — it's the deterministic, non-LLM
  part that's the actual hard engineering here.

## 1. Dashboard tour (1 min)

Open http://localhost:5173. Show the seeded repository card: name,
language, last-analyzed status (should be `READY`, not `STALE`). This is
the entry point to everything else below.

## 2. Assistant chat — grounded Q&A (3-5 min)

Open the repository → **Assistant**. Ask these in order; each is chosen
to show a different capability:

1. **"Where is authentication implemented?"**
   Expect an answer citing `AuthService.login` (and likely
   `app/security/tokens.py`) with real file/line citations — not a vague
   description.
2. **"What does AuthService.login call?"**
   Expect `UserRepository.find_by_email` and
   `TokenService.create_access_token` — this is graph-sourced, not the
   LLM guessing from the function's name.
3. **"What does validate_credentials do?"**
   There are **two** functions with this exact name in different
   modules. A good answer either asks for clarification or clearly
   distinguishes both — this demos symbol-ambiguity handling rather than
   silently picking one.
4. **"Who calls format_user_display_name?"**
   Expect an answer saying effectively "nobody" / "no callers found" —
   this is a real, correct, useful answer about an intentionally
   isolated function, not a failure.
5. **"What tests cover AuthService.login?"**
   Expect `tests/test_auth.py` — demos the related-tests signal.

Every answer should show inline citation markers (`[E1]`, `[E2]`, ...)
you can click through to the real source line — that click-through is
the point: the LLM explains, the graph/vector retrieval is what actually
found the evidence.

## 3. Graph explorer (1-2 min)

Open the repository → **Graph**. Search for `AuthService` and open it.
Show:
- The `CALLS` edges out to `UserRepository.find_by_email` and
  `TokenService.create_access_token`.
- Expand `UserRepository` and show its `EXTENDS` edge to `BaseRepository`
  — a real inheritance relationship, not inferred text.

## 4. Impact analysis (2-3 min)

Open the repository → **Impact Analysis** → search `AuthService.login` →
**Analyze**. This is the centerpiece: deterministic graph traversal, with
an optional LLM summary layered on top (clearly separated — see
ARCHITECTURE.md).

Point out:
- **Direct vs. transitive dependents**: `login_endpoint` is a direct
  caller; the `POST /login` API endpoint is reached transitively.
- **API exposure**: because a public endpoint depends on it, risk scoring
  weights this higher than an equivalent internal-only function would
  score (`IMPACT_WEIGHT_API_EXPOSURE` in `.env.example`) — explicitly a
  structural heuristic, never presented as a probability of failure.
- **The natural-language summary** (if an LLM is configured) sits
  alongside, not instead of, the deterministic result above it.

Contrast this with `format_user_display_name` (from step 2.4) — analyze
it too and show an empty/near-empty impact set, demonstrating the tool
correctly reports "nothing/little depends on this" instead of inventing
risk.

## 5. API, not just UI (optional, 1 min)

Everything above has a REST equivalent — useful to show this isn't just
a UI demo:

```bash
curl -X POST http://localhost:8000/api/v1/repositories/<repository_id>/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Where is authentication implemented?"}'
```

Windows PowerShell: use `curl.exe` (see
[HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) step 12 for the full
quoting example). See [API_SPEC.md](../API_SPEC.md) for every endpoint.

## 6. If asked "does this need internet/an API key?"

Good opportunity to show the cost story directly:

```bash
make demo-check
```
(or `python scripts/run_demo_checks.py`) — passes using a built-in fake
LLM, proving the entire retrieval/citation/impact pipeline works with
`LLM_API_KEY=changeme`, zero network calls to any LLM. See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#demo-check-and-the-fake-llm).

## Timing summary

| Section | Time |
|---|---|
| Dashboard tour | ~1 min |
| Assistant chat (5 questions) | ~4 min |
| Graph explorer | ~2 min |
| Impact analysis (2 targets) | ~3 min |
| API/cost story (optional) | ~1 min |
| **Total** | **~10 min** |

Trim the Assistant chat questions to 2-3 if you're short on time —
question 2 (call graph) and question 4 (isolated function) are the two
most convincing on their own.

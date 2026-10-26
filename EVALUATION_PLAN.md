# Evaluation Plan

This system makes a specific claim: grounding answers in a deterministic
graph plus vector retrieval is more trustworthy than an LLM-only or
vector-only approach. The evaluation plan exists to test that claim, not
just to check that code runs.

## Fixture repositories

A small set of hand-built or curated Python repositories, checked in (or
scripted to generate) purely for testing, each with a **known-correct**
answer key:

- A **small synthetic repo** (a few files, a handful of classes/functions,
  deliberately including: inheritance, a call chain 3+ levels deep, an
  external dependency import, and one FastAPI-style route) with a
  hand-authored expected graph (exact node/edge counts and identities).
- One or two **real-world small/medium open-source Python repos** (pinned
  to a specific commit) for more realistic parsing and retrieval tests
  where hand-authoring the full expected graph isn't feasible, but specific
  spot-checks are.

These fixtures back all four evaluation dimensions below and are the
things referenced by [AGENTS.md](AGENTS.md)'s "definition of done."

## 1. Parsing / graph-construction correctness

**What**: does the deterministic Tree-sitter extraction produce the graph
it should, per [DATA_MODEL.md](DATA_MODEL.md)?

**How**:
- Pytest unit tests parse each fixture file and assert exact counts and
  identities of nodes/edges (e.g. "file `models.py` produces exactly one
  `Class` node named `Invoice` with an `EXTENDS` edge to `BaseModel`").
- Edge cases explicitly tested: nested classes, decorated functions,
  `async def`, star imports, relative imports, multiple inheritance.
- A known-failure case (e.g. a call through `getattr`) is tested to confirm
  it is *not* silently fabricated as a resolved `CALLS` edge — the system
  should omit what it can't resolve rather than guess.

**Target**: 100% match against the hand-authored graph for the synthetic
fixture; no crashes and a bounded, logged error count on the real-world
fixtures.

## 2. Retrieval quality

**What**: given a natural-language question about a fixture repo, does the
system retrieve (and ultimately cite) the right source location?

**How**:
- A labeled QA set: ~20-40 question/answer pairs per fixture repo, each
  with the expected `qualified_name`/`file_path`/`line range` that should
  appear in the answer's citations.
- Measure **hit@k** (is the correct location present in the top-k retrieved
  items) separately for: GraphRetriever alone, VectorRetriever alone, and
  the hybrid orchestrator — this directly demonstrates whether hybrid
  retrieval outperforms either component alone, which is the project's core
  hypothesis.
- Structural questions ("what calls X", "what does X depend on") are
  expected to be answered primarily via GraphRetriever; semantic questions
  ("where is rate limiting implemented") primarily via VectorRetriever.
  The QA set should include both kinds so the split is measurable, not
  assumed.

**Target**: hybrid hit@k ≥ either component alone, on both question
categories.

## 3. Change-impact-analysis accuracy

**What**: does the impact-analysis traversal find the correct transitive
dependent set?

**How**:
- For each fixture repo, hand-derive the true dependent set for several
  target symbols at a fixed depth (by manual code reading, independent of
  the system).
- Compare the system's `impacted` list (see [API_SPEC.md](API_SPEC.md))
  against the ground truth using precision and recall.
- Separately verify the `summary` field never names an entity absent from
  `impacted` (LLM must not add facts the graph didn't produce — rule 2).

**Target**: precision and recall on the synthetic fixture close to 1.0
(it's small enough to fully control); recall reported (not necessarily 1.0)
on the real-world fixture, with any misses attributable to documented
limitations (e.g. dynamic dispatch) rather than bugs.

## 4. Answer faithfulness / citation-groundedness

**What**: does every citation in a generated answer actually correspond to
retrieved context, and does the prose avoid asserting relationships the
graph doesn't contain?

**How**:
- Automated check: for every citation returned by `/query` or `/impact`,
  assert its `(file_path, start_line, end_line)` appears in the context
  that was actually passed to the LLM for that request. This is fully
  scriptable and should run as part of the Pytest suite against recorded
  fixtures/mocked LLM responses, not just manually.
- Spot-check (manual, periodic): read a sample of generated answers on the
  real-world fixture repo and check for claims not supported by any
  retrieved chunk or graph fact.

**Target**: zero ungrounded citations on the automated check for the
fixture suite (this is treated as a correctness bug, not a quality nit —
see [AGENTS.md](AGENTS.md)).

## 5. Performance

**What**: does ingestion and query latency stay usable at the repo sizes
the MVP targets?

**How**: measure and record (not necessarily gate CI on):
- Ingestion wall-clock time vs. file count / total LOC.
- `/query` and `/impact` p50/p95 latency on the fixture repos.

**Target**: documented numbers, not a hard SLA — the MVP's goal is
correctness and grounding, not throughput. Regressions worth flagging: an
order-of-magnitude slowdown between milestones.

## Regression testing in CI

- The parsing correctness tests (§1) and citation-groundedness tests (§4)
  run on every change via Pytest, since they don't require a live LLM call
  (mocked/recorded LLM responses are used).
- Retrieval quality (§2) and impact accuracy (§3) numbers are recomputed
  whenever GraphRetriever, VectorRetriever, the orchestrator, or the
  chunking strategy changes, and the resulting numbers are recorded in the
  PR/change description rather than silently trusted.

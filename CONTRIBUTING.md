# Contributing

## Before you start

Read [AGENTS.md](AGENTS.md) first — it contains the ten architectural rules
this project must not violate, and they take priority over anything below.

## Development environment

Prerequisites (once implementation begins):

- Python 3.12
- Node.js (LTS) + a package manager compatible with the frontend's
  `package.json` (npm)
- Docker + Docker Compose (for Neo4j, and later the full stack)

Setup flow:

```
cp .env.example .env      # fill in required values, see below
make setup                # install backend + frontend dependencies
make up                   # start Neo4j (and other services) via Docker Compose
```

See [.env.example](.env.example) for the full list of configuration
variables and [Makefile](Makefile) for available tasks.

## Project layout

See [AGENTS.md](AGENTS.md) for the planned `backend/` / `frontend/`
directory structure. Keep new code inside the existing module boundaries
(`ingestion/`, `graph/`, `vector/`, `retrieval/`, `impact/`, `api/`) rather
than introducing new top-level packages for one-off features.

## Coding conventions

### Python (backend)

- **Ruff** is the linter and formatter — run it before committing; CI
  should fail on Ruff findings, not just warn.
- **mypy** type-checks the backend. Public functions and module boundaries
  (especially anything in `graph/`, `vector/`, `retrieval/`, `impact/`)
  must carry type hints; internal helpers should too where it isn't noisy.
- Prefer explicit, narrow functions over clever abstractions — see the
  "avoid unnecessary abstractions" rule in [AGENTS.md](AGENTS.md). A new
  base class or plugin interface needs a concrete second use case before it
  is justified.
- Cypher queries live alongside the graph code that issues them (in
  `graph/`), not scattered through API handlers, so the `repository_id`
  filtering convention (see [DATA_MODEL.md](DATA_MODEL.md)) is easy to
  audit in one place.

### TypeScript / React (frontend)

- **ESLint** + **Prettier** enforced; TypeScript in strict mode.
- Components that render graph data (Cytoscape.js) should keep data-shaping
  logic separate from rendering, so the API response shapes in
  [API_SPEC.md](API_SPEC.md) can change without a rewrite of rendering
  code.

## Testing expectations

- **Backend (Pytest)**:
  - Parsing/graph-construction logic is tested against fixture Python files
    with asserted node/edge outcomes (see
    [EVALUATION_PLAN.md](EVALUATION_PLAN.md) §1) — this is the highest-value
    test surface in the project, since it's the deterministic core the
    rest of the system depends on being correct.
  - Retrieval and impact-analysis logic is tested with recorded/mocked LLM
    responses so tests are deterministic and don't require live API calls
    or incur cost.
  - New API endpoints get at least one request/response contract test
    against [API_SPEC.md](API_SPEC.md).
- **Frontend (Vitest)**: component tests for the chat UI, graph explorer,
  and impact-analysis view, at minimum covering rendering of a typical API
  response and an error/empty state.
- A change to `graph/`, `vector/`, or `retrieval/` that isn't accompanied
  by a test is treated as incomplete, not just "light on tests" — these are
  the modules the project's core correctness claim rests on.

## Commits and branches

- Branch names: `type/short-description` (e.g. `feat/impact-traversal`,
  `fix/import-resolution`).
- Commit messages explain *why*, not just *what* — the diff already shows
  what changed.
- Update the relevant documentation file(s) ([ARCHITECTURE.md](ARCHITECTURE.md),
  [DATA_MODEL.md](DATA_MODEL.md), [API_SPEC.md](API_SPEC.md)) in the same
  change when behavior they describe changes, per [AGENTS.md](AGENTS.md).

## Pull requests

- Keep PRs scoped to one milestone item from
  [PROJECT_PLAN.md](PROJECT_PLAN.md) where possible.
- Call out explicitly if a PR touches anything listed as a non-goal — that
  should trigger a scope discussion, not a silent merge.

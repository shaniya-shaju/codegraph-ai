# Scripts

One-off and maintenance scripts that don't belong in the backend app
package. Each is a thin CLI over an application service — no duplicated
business logic — and adds `backend/` to `sys.path` at startup so it can
import the `app` package without a separate install step.

- **`rebuild_vector_index.py`** — reindex one repository's vector store
  (re-scans/re-parses its existing on-disk workspace, then delegates to
  `app.indexing.indexing_service`). Never re-uploads/re-clones and never
  touches the knowledge graph.

  ```
  python scripts/rebuild_vector_index.py <repository_id> [--force]
  ```

- **`inspect_vector_search.py`** — run a semantic search against an
  already-indexed repository and print the ranked results (via
  `app.indexing.retrieval_service`).

  ```
  python scripts/inspect_vector_search.py <repository_id> "<query>" [--top-k N]
  ```

- **`inspect_hybrid_retrieval.py`** — run one question through the full
  hybrid retrieval pipeline (query analysis, retrieval planning, symbol
  resolution, vector/graph retrieval, fusion/ranking, budgeting) via
  `app.rag.hybrid_retriever`, and print intent, entities, resolved
  symbols, the retrieval plan, ranked evidence with score breakdowns, and
  diagnostics. Useful for debugging retrieval before LLM answer
  generation exists.

  ```
  python scripts/inspect_hybrid_retrieval.py \
      --repository-id <id> --question "Which functions call login?" --mode hybrid
  ```

All scripts assume the backend's Python environment (see
[backend/pyproject.toml](../backend/pyproject.toml)) is active and that
`DATABASE_URL` / `CHROMA_PERSIST_DIRECTORY` / embedding settings resolve
to the same values the running API uses (see [.env.example](../.env.example)).

#!/usr/bin/env python3
"""Debug one hybrid-retrieval question end-to-end before LLM answer
generation exists.

Uses the same application services the API uses
(app.rag.hybrid_retriever.retrieve) — no duplicated business logic.

Usage:
    python scripts/inspect_hybrid_retrieval.py \
        --repository-id <id> \
        --question "Which functions call login?" \
        --mode hybrid
"""

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.domain.rag.enums import RetrievalMode  # noqa: E402
from app.domain.rag.models import HybridRetrievalResult  # noqa: E402
from app.graph.neo4j_client import get_neo4j_client  # noqa: E402
from app.indexing.chroma_store import get_vector_store  # noqa: E402
from app.indexing.sentence_transformer_provider import get_embedding_provider  # noqa: E402
from app.rag.hybrid_retriever import retrieve  # noqa: E402
from app.rag.llm_provider import get_structured_llm_provider  # noqa: E402


def _print_result(result: HybridRetrievalResult) -> None:
    analysis = result.analysis
    print("=" * 78)
    print(f"Question:            {result.question}")
    print(f"Intent:               {analysis.primary_intent.value}")
    print(f"Secondary intents:    {[i.value for i in analysis.secondary_intents]}")
    print(f"Analysis strategy:    {analysis.analysis_strategy}")
    print(f"Confidence:           {analysis.confidence}")
    print()
    print("Entities:")
    print(f"  symbols:            {analysis.symbols}")
    print(f"  function_names:     {analysis.function_names}")
    print(f"  class_names:        {analysis.class_names}")
    print(f"  file_paths:         {analysis.file_paths}")
    print(f"  api_routes:         {analysis.api_routes}")
    print()
    print("Resolved symbols:")
    for resolution in result.resolved_symbols:
        symbol = resolution.resolved_symbol
        location = f"{symbol.file_path}:{symbol.start_line}" if symbol and symbol.file_path else "-"
        print(
            f"  {resolution.query!r} -> status={resolution.status.value} "
            f"symbol={symbol.qualified_name if symbol else None} ({location}) "
            f"candidates={len(resolution.candidates)}"
        )
    print()
    plan = result.plan
    print("Retrieval plan:")
    print(f"  use_vector={plan.use_vector} use_graph={plan.use_graph} use_symbol_search={plan.use_symbol_search}")
    print(f"  vector_top_k={plan.vector_top_k} graph_depth={plan.graph_depth} symbol_limit={plan.symbol_limit}")
    print(f"  graph_operations={[op.value for op in plan.graph_operations]}")
    print()
    print(
        f"Candidates: vector={result.total_vector_candidates} graph={result.total_graph_candidates} "
        f"symbol={result.total_symbol_candidates} deduplicated={result.deduplicated_count} "
        f"returned={result.returned_count} truncated={result.truncated}"
    )
    print()
    print("Top evidence:")
    for i, ranked in enumerate(result.evidence, start=1):
        ev = ranked.evidence
        location = f"{ev.file_path}:{ev.start_line}-{ev.end_line}" if ev.file_path else "-"
        c = ranked.score_components
        print(f"  [{i}] hybrid_score={ranked.hybrid_score:.3f} sources={[s.value for s in ranked.sources]}")
        print(f"      type={ev.evidence_type.value} qualified_name={ev.qualified_name} location={location}")
        print(f"      score_components: vector={c.vector:.2f} exact={c.exact:.2f} graph={c.graph:.2f} intent={c.intent:.2f}")
        print(f"      content: {ev.content[:120]!r}")
    print()
    d = result.diagnostics
    print("Diagnostics:")
    print(f"  total={d.retrieval_duration_ms}ms analysis={d.analysis_duration_ms}ms vector={d.vector_duration_ms}ms graph={d.graph_duration_ms}ms")
    print(f"  fallbacks_used={d.fallbacks_used}")
    print(f"  warnings={d.warnings}")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--mode", choices=["vector", "graph", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    client = get_neo4j_client()
    embedding_provider = get_embedding_provider()
    vector_store = get_vector_store()
    llm_provider = get_structured_llm_provider()

    result = asyncio.run(
        retrieve(
            repository_id=args.repository_id,
            question=args.question,
            mode=RetrievalMode(args.mode),
            top_k=args.top_k,
            settings=settings,
            neo4j_client=client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm_provider,
        )
    )
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

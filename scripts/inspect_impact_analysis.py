#!/usr/bin/env python3
"""Debug/demo one deterministic change-impact analysis end-to-end.

Uses the same application service the API uses
(app.impact.service.get_impact_analysis) — no duplicated business logic.

Usage:
    python scripts/inspect_impact_analysis.py \
        --repository-id <id> \
        --symbol-id <id> \
        --depth 3
"""

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.domain.impact.models import ImpactAnalysisResult  # noqa: E402
from app.graph.exceptions import GraphError  # noqa: E402
from app.graph.neo4j_client import get_neo4j_client  # noqa: E402
from app.impact import service as impact_service  # noqa: E402
from app.impact.exceptions import ImpactError  # noqa: E402


def _print_result(result: ImpactAnalysisResult) -> None:
    t = result.target
    print("=" * 78)
    print("Target")
    print(f"  qualified_name: {t.qualified_name or t.name}")
    print(f"  type:           {t.target_type.value}")
    print(f"  location:       {t.file_path}:{t.start_line}-{t.end_line}")
    print()
    print(f"Risk score / level: {result.risk_score:.1f}/100 ({result.risk_level.value})")
    print("  (a structural change-impact-risk heuristic — NOT a probability of failure)")
    print()

    print(f"Direct callers ({len(result.direct_callers)}):")
    for s in result.direct_callers:
        print(f"  - {s.qualified_name} [{s.file_path}:{s.start_line}] dist={s.distance}")
        print(f"      reason: {s.reason}")

    print(f"\nTransitive dependents ({len(result.transitive_dependents)}):")
    for s in result.transitive_dependents:
        print(f"  - {s.qualified_name} [{s.file_path}:{s.start_line}] dist={s.distance}")
        print(f"      path: {' -> '.join(s.path)}")
        print(f"      reason: {s.reason}")

    print(f"\nAffected API endpoints ({len(result.affected_endpoints)}):")
    for e in result.affected_endpoints:
        print(f"  - {e.http_method} {e.route_path} (handler={e.handler_qualified_name}, "
              f"distance={e.distance_from_target})")
        print(f"      reason: {e.impact_reason}")

    print(f"\nAffected files ({len(result.affected_files)}):")
    for f in result.affected_files:
        print(f"  - {f.file_path}: {f.affected_symbol_count} symbol(s), "
              f"min_distance={f.minimum_distance}, types={[t.value for t in f.impact_types]}")

    print(f"\nAffected modules ({len(result.affected_modules)}):")
    for m in result.affected_modules:
        print(f"  - {m.module_name}: {m.affected_symbol_count} symbol(s), "
              f"min_distance={m.minimum_distance}")

    print(f"\nDownstream dependencies ({len(result.downstream_dependencies)}):")
    for s in result.downstream_dependencies:
        print(f"  - {s.qualified_name} [{s.file_path}:{s.start_line}] dist={s.distance}")
        print(f"      reason: {s.reason}")

    print(f"\nInheritance impacts ({len(result.inheritance_impacts)}):")
    print(f"  inheriting_classes: {[s.qualified_name for s in result.inheriting_classes]}")
    print(f"  base_classes:       {[s.qualified_name for s in result.base_classes]}")

    print(f"\nRelated tests ({len(result.related_tests)}), "
          f"status={result.test_relationship_status.value}:")
    for s in result.related_tests:
        print(f"  - {s.qualified_name} [{s.file_path}:{s.start_line}]")

    print("\nRisk signals (contribution per signal):")
    for sig in result.risk_signals:
        print(
            f"  - {sig.signal_type.value:<32} raw={sig.raw_value:>6.2f} "
            f"normalized={sig.normalized_value:.2f} contribution={sig.contribution:6.2f}"
        )
        print(f"      {sig.explanation}")
    print(f"  TOTAL: {sum(s.contribution for s in result.risk_signals):.2f} "
          f"(reported risk_score={result.risk_score:.1f}, capped at 100)")

    d = result.diagnostics
    print("\nTraversal diagnostics:")
    print(f"  analysis_duration_ms={d.analysis_duration_ms} nodes_visited={d.nodes_visited} "
          f"edges_traversed={d.edges_traversed} paths_examined={d.paths_examined} "
          f"cycles_detected={d.cycles_detected}")
    print(f"  traversal_depth={result.traversal_depth} total_impacted_symbols="
          f"{result.total_impacted_symbols} truncated={result.truncated} "
          f"(reason={d.truncated_reason})")

    print("\nLimitations:")
    for limitation in result.limitations:
        print(f"  - {limitation}")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--symbol-id", default=None)
    parser.add_argument("--qualified-name", default=None)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--max-nodes", type=int, default=None)
    parser.add_argument("--no-downstream", action="store_true")
    parser.add_argument("--no-tests", action="store_true")
    args = parser.parse_args()

    if not args.symbol_id and not args.qualified_name:
        parser.error("Either --symbol-id or --qualified-name is required.")

    settings = get_settings()
    client = get_neo4j_client()

    try:
        result = impact_service.get_impact_analysis(
            client,
            settings,
            repository_id=args.repository_id,
            symbol_id=args.symbol_id,
            qualified_name=args.qualified_name,
            max_depth=args.depth,
            max_nodes=args.max_nodes,
            include_downstream=not args.no_downstream,
            include_tests=not args.no_tests,
        )
    except ImpactError as exc:
        print(f"Impact analysis failed: {exc}", file=sys.stderr)
        return 1
    except GraphError as exc:
        print(f"Could not reach the knowledge graph: {exc}", file=sys.stderr)
        return 1

    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

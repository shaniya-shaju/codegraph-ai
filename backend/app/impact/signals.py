"""Deterministic impact-signal computation — see "Deterministic impact
signals". Pure functions over already-aggregated impact data; no graph
access and no risk-score math here (that's risk_scorer.py) — see the
impact-analysis task's package layout note about keeping these separate.

Every ``raw_value`` is normalized into ``[0.0, 1.0]`` via
``min(raw / reference_count, 1.0)`` before being weighted (see "Do not
allow one huge caller count to create an unbounded score." /
"Normalize raw counts before applying weights."). Reference counts and
weights are both configurable, untuned heuristics (Settings.impact_*).
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.impact.enums import ImpactSignalType, TestRelationshipStatus
from app.domain.impact.models import ImpactSignal


def _normalize(raw: float, reference: float) -> float:
    if reference <= 0:
        return 1.0 if raw > 0 else 0.0
    return min(raw / reference, 1.0)


@dataclass(frozen=True)
class SignalInputs:
    direct_caller_count: int
    transitive_dependent_count: int  # strictly distance >= 2, excludes direct callers
    affected_file_count: int
    affected_module_count: int
    api_endpoint_count: int
    cross_module_dependent_count: int
    external_dependency_count: int
    inheritance_impact_count: int
    centrality_in_degree: int
    centrality_out_degree: int
    test_relationship_status: TestRelationshipStatus


def compute_signals(inputs: SignalInputs, settings: Settings) -> list[ImpactSignal]:
    centrality_raw = inputs.centrality_in_degree + inputs.centrality_out_degree
    # Presence of known related tests is treated as a small risk-reducing
    # signal (a safety net exists); no known references (or an unknown/
    # truncated search) is treated as the higher-risk case — this
    # direction is a documented design decision, not specified literally
    # by the task.
    has_known_tests = inputs.test_relationship_status is TestRelationshipStatus.KNOWN_RELATED_TESTS
    test_signal_raw = 0.0 if has_known_tests else 1.0

    definitions: list[tuple[ImpactSignalType, float, float, float, str]] = [
        (
            ImpactSignalType.DIRECT_CALLER_COUNT,
            float(inputs.direct_caller_count),
            settings.impact_reference_direct_callers,
            settings.impact_weight_direct_callers,
            f"{inputs.direct_caller_count} symbol(s) directly call the target.",
        ),
        (
            ImpactSignalType.TRANSITIVE_DEPENDENT_COUNT,
            float(inputs.transitive_dependent_count),
            settings.impact_reference_transitive_dependents,
            settings.impact_weight_transitive_dependents,
            f"{inputs.transitive_dependent_count} symbol(s) depend on the target transitively "
            "within the configured graph depth.",
        ),
        (
            ImpactSignalType.AFFECTED_FILE_COUNT,
            float(inputs.affected_file_count),
            settings.impact_reference_affected_files,
            settings.impact_weight_affected_files,
            f"{inputs.affected_file_count} file(s) contain a potentially affected symbol.",
        ),
        (
            ImpactSignalType.AFFECTED_MODULE_COUNT,
            float(inputs.affected_module_count),
            settings.impact_reference_affected_files,
            0.0,
            f"{inputs.affected_module_count} module(s) contain a potentially affected symbol "
            "(informational — not separately weighted; see CROSS_MODULE_DEPENDENCY).",
        ),
        (
            ImpactSignalType.PUBLIC_API_EXPOSURE,
            float(inputs.api_endpoint_count),
            settings.impact_reference_api_endpoints,
            settings.impact_weight_api_exposure,
            f"{inputs.api_endpoint_count} API endpoint(s) depend on the target.",
        ),
        (
            ImpactSignalType.CROSS_MODULE_DEPENDENCY,
            float(inputs.cross_module_dependent_count),
            settings.impact_reference_cross_module,
            settings.impact_weight_cross_module,
            f"{inputs.cross_module_dependent_count} dependent(s) live outside the target's own "
            "module.",
        ),
        (
            ImpactSignalType.EXTERNAL_DEPENDENCY_INTERACTION,
            float(inputs.external_dependency_count),
            settings.impact_reference_external_dependencies,
            settings.impact_weight_external_dependency,
            f"{inputs.external_dependency_count} external dependency(ies) are deterministically "
            "known to be involved.",
        ),
        (
            ImpactSignalType.INHERITANCE_IMPACT,
            float(inputs.inheritance_impact_count),
            settings.impact_reference_inheritance,
            settings.impact_weight_inheritance,
            f"{inputs.inheritance_impact_count} class(es) are related to the target through "
            "inheritance.",
        ),
        (
            ImpactSignalType.GRAPH_CENTRALITY,
            float(centrality_raw),
            settings.impact_reference_centrality,
            settings.impact_weight_centrality,
            f"Local structural centrality (in-degree + out-degree of CALLS edges) is "
            f"{centrality_raw} — not PageRank or a comprehensive centrality measure.",
        ),
        (
            ImpactSignalType.RELATED_TEST_SIGNAL,
            test_signal_raw,
            1.0,
            settings.impact_weight_test_signal,
            _test_signal_explanation(inputs.test_relationship_status),
        ),
    ]

    signals = []
    for signal_type, raw, reference, weight, explanation in definitions:
        normalized = _normalize(raw, reference)
        signals.append(
            ImpactSignal(
                signal_type=signal_type,
                raw_value=raw,
                normalized_value=normalized,
                contribution=normalized * weight,
                explanation=explanation,
            )
        )
    return signals


def _test_signal_explanation(status: TestRelationshipStatus) -> str:
    if status is TestRelationshipStatus.KNOWN_RELATED_TESTS:
        return "Known related tests exist (a graph-verified relationship to a test symbol)."
    if status is TestRelationshipStatus.UNKNOWN:
        return (
            "Test-relationship search was truncated before it could be conclusive — this is "
            "NOT a claim that no tests exist."
        )
    return (
        "No known graph relationship to a test symbol was found — this is NOT a claim that no "
        "tests exist for this code."
    )

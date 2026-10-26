"""Unit tests for app.impact.mappers — target-type mapping, module
derivation, and the impact-result-to-evidence translation used by the
natural-language integration."""

from app.domain.graph.enums import NodeLabel
from app.domain.impact.enums import ImpactTargetType, ImpactType, RiskLevel, TestRelationshipStatus
from app.domain.impact.models import (
    ImpactAnalysisResult,
    ImpactDiagnostics,
    ImpactedSymbol,
    ImpactTarget,
)
from app.impact import mappers


class TestTargetTypeForLabel:
    def test_supported_labels_map_correctly(self) -> None:
        assert mappers.target_type_for_label(NodeLabel.FUNCTION) is ImpactTargetType.FUNCTION
        assert mappers.target_type_for_label(NodeLabel.METHOD) is ImpactTargetType.METHOD
        assert mappers.target_type_for_label(NodeLabel.CLASS) is ImpactTargetType.CLASS
        assert (
            mappers.target_type_for_label(NodeLabel.API_ENDPOINT) is ImpactTargetType.API_ENDPOINT
        )

    def test_unsupported_labels_return_none(self) -> None:
        assert mappers.target_type_for_label(NodeLabel.MODULE) is None
        assert mappers.target_type_for_label(NodeLabel.FILE) is None
        assert mappers.target_type_for_label(NodeLabel.EXTERNAL_DEPENDENCY) is None


class TestModuleOf:
    def test_derives_from_qualified_name(self) -> None:
        assert mappers.module_of("pkg.mod.func", fallback_file_path=None) == "pkg.mod"

    def test_top_level_qualified_name_returns_itself(self) -> None:
        assert mappers.module_of("func", fallback_file_path=None) == "func"

    def test_falls_back_to_file_directory(self) -> None:
        assert mappers.module_of(None, fallback_file_path="pkg/mod.py") == "pkg"

    def test_falls_back_to_dot_for_root_file(self) -> None:
        assert mappers.module_of(None, fallback_file_path="mod.py") == "."

    def test_unknown_when_nothing_available(self) -> None:
        assert mappers.module_of(None, fallback_file_path=None) == "<unknown>"


def _result(**overrides: object) -> ImpactAnalysisResult:
    base = dict(
        repository_id="repo-1",
        target=ImpactTarget(
            symbol_id="t1",
            qualified_name="pkg.target",
            name="target",
            target_type=ImpactTargetType.FUNCTION,
            file_path="pkg/mod.py",
            start_line=1,
            end_line=5,
        ),
        risk_score=10.0,
        risk_level=RiskLevel.LOW,
        risk_signals=[],
        direct_callers=[],
        transitive_dependents=[],
        downstream_dependencies=[],
        affected_endpoints=[],
        affected_files=[],
        affected_modules=[],
        inheritance_impacts=[],
        inheriting_classes=[],
        base_classes=[],
        related_tests=[],
        test_relationship_status=TestRelationshipStatus.NO_KNOWN_TEST_REFERENCES,
        traversal_depth=2,
        total_impacted_symbols=0,
        truncated=False,
        limitations=[],
        diagnostics=ImpactDiagnostics(
            analysis_duration_ms=1,
            nodes_visited=1,
            edges_traversed=0,
            paths_examined=0,
            cycles_detected=0,
        ),
    )
    base.update(overrides)
    return ImpactAnalysisResult(**base)  # type: ignore[arg-type]


class TestImpactResultToEvidence:
    def test_summary_item_is_always_first_and_citable(self) -> None:
        result = _result()
        evidence = mappers.impact_result_to_evidence(result)
        assert len(evidence) == 1
        assert evidence[0].file_path == "pkg/mod.py"
        assert "Risk score" in evidence[0].content

    def test_impacted_symbols_without_file_path_are_skipped(self) -> None:
        symbol = ImpactedSymbol(
            symbol_id="c1",
            qualified_name="pkg.caller",
            symbol_type="Function",
            file_path=None,
            start_line=None,
            end_line=None,
            impact_type=ImpactType.DIRECT_CALLER,
            distance=1,
            reason="calls target",
        )
        result = _result(direct_callers=[symbol])
        evidence = mappers.impact_result_to_evidence(result)
        # Only the summary item — the file-less symbol is skipped.
        assert len(evidence) == 1

    def test_impacted_symbols_with_file_path_become_citable_evidence(self) -> None:
        symbol = ImpactedSymbol(
            symbol_id="c1",
            qualified_name="pkg.caller",
            symbol_type="Function",
            file_path="pkg/caller.py",
            start_line=3,
            end_line=4,
            impact_type=ImpactType.DIRECT_CALLER,
            distance=1,
            reason="Directly calls pkg.target.",
        )
        result = _result(direct_callers=[symbol])
        evidence = mappers.impact_result_to_evidence(result)
        assert len(evidence) == 2
        item = evidence[1]
        assert item.file_path == "pkg/caller.py"
        assert item.content == "Directly calls pkg.target."
        assert item.qualified_name == "pkg.caller"

    def test_truncation_is_mentioned_in_summary(self) -> None:
        result = _result(truncated=True)
        text = mappers.impact_summary_text(result)
        assert "truncated" in text.lower()

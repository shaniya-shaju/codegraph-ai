"""Unit tests for app.impact.explanation — the optional grounded LLM
explain-only layer. Uses FakeAnswerLLMProvider (tests/fakes.py) — no
external model calls."""

import pytest

from app.domain.impact.enums import ImpactTargetType, RiskLevel, TestRelationshipStatus
from app.domain.impact.models import ImpactAnalysisResult, ImpactDiagnostics, ImpactTarget
from app.impact import explanation
from app.rag.exceptions import LLMAnalysisError
from tests.fakes import FakeAnswerLLMProvider


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
        risk_score=42.0,
        risk_level=RiskLevel.MEDIUM,
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
        limitations=["The structural risk score is a heuristic."],
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


class TestBuildExplanationUserPrompt:
    def test_wraps_result_in_delimiters(self) -> None:
        prompt = explanation.build_explanation_user_prompt(_result())
        assert "<<<IMPACT_RESULT_START>>>" in prompt
        assert "<<<IMPACT_RESULT_END>>>" in prompt
        start = prompt.index("<<<IMPACT_RESULT_START>>>")
        end = prompt.index("<<<IMPACT_RESULT_END>>>")
        assert "pkg.target" in prompt[start:end]

    def test_includes_risk_score_and_level(self) -> None:
        prompt = explanation.build_explanation_user_prompt(_result())
        assert "42.0/100" in prompt
        assert "MEDIUM" in prompt


class TestFindUnsupportedIdentifiers:
    def test_known_identifiers_are_not_flagged(self) -> None:
        result = _result()
        text = "This affects pkg.target only."
        assert explanation._find_unsupported_identifiers(text, result) == []

    def test_fabricated_qualified_name_is_flagged(self) -> None:
        result = _result()
        text = "This also affects app.billing.invoice.charge, which was never in the result."
        found = explanation._find_unsupported_identifiers(text, result)
        assert "app.billing.invoice.charge" in found


class TestExplainImpact:
    async def test_returns_explanation_text(self) -> None:
        provider = FakeAnswerLLMProvider(
            structured_result=explanation.ImpactExplanationOutput(
                explanation="This function has moderate risk due to a few direct callers."
            )
        )
        result = await explanation.explain_impact(provider, _result(), timeout_seconds=5)
        assert "moderate risk" in result.explanation
        assert result.warnings == []

    async def test_flags_unsupported_identifiers_as_warning(self) -> None:
        provider = FakeAnswerLLMProvider(
            structured_result=explanation.ImpactExplanationOutput(
                explanation="This also affects app.billing.invoice.charge unexpectedly."
            )
        )
        result = await explanation.explain_impact(provider, _result(), timeout_seconds=5)
        assert result.warnings
        assert "app.billing.invoice.charge" in result.warnings[0]

    async def test_llm_error_is_wrapped(self) -> None:
        provider = FakeAnswerLLMProvider(structured_error=LLMAnalysisError("boom"))
        with pytest.raises(LLMAnalysisError):
            await explanation.explain_impact(provider, _result(), timeout_seconds=5)

    async def test_system_prompt_forbids_adding_new_impact_data(self) -> None:
        provider = FakeAnswerLLMProvider(
            structured_result=explanation.ImpactExplanationOutput(explanation="ok")
        )
        await explanation.explain_impact(provider, _result(), timeout_seconds=5)
        call = provider.generate_structured_calls[0]
        assert "Do not add any affected symbol" in call["system_prompt"]
        assert "not a probability" in call["system_prompt"]

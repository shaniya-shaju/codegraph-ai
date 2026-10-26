"""Unit tests for app.impact.risk_scorer — the score-is-sum-of-
contributions invariant, the documented cap, and risk-level thresholds."""

import pytest

from app.core.config import Settings
from app.domain.impact.enums import ImpactSignalType, RiskLevel
from app.domain.impact.models import ImpactSignal
from app.impact.risk_scorer import RISK_SCORE_CAP, classify_risk_level, compute_risk_score


def _signal(contribution: float) -> ImpactSignal:
    return ImpactSignal(
        signal_type=ImpactSignalType.DIRECT_CALLER_COUNT,
        raw_value=1.0,
        normalized_value=1.0,
        contribution=contribution,
        explanation="test",
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        impact_risk_medium_threshold=25.0,
        impact_risk_high_threshold=50.0,
        impact_risk_critical_threshold=75.0,
    )


class TestComputeRiskScore:
    def test_score_equals_sum_of_contributions_below_cap(self) -> None:
        signals = [_signal(10.0), _signal(20.0), _signal(5.5)]
        assert compute_risk_score(signals) == pytest.approx(35.5)

    def test_score_is_capped_at_100(self) -> None:
        signals = [_signal(60.0), _signal(60.0)]
        assert compute_risk_score(signals) == RISK_SCORE_CAP

    def test_empty_signal_list_scores_zero(self) -> None:
        assert compute_risk_score([]) == 0.0

    def test_deterministic_repeated_scoring(self) -> None:
        signals = [_signal(12.3), _signal(7.7)]
        first = compute_risk_score(signals)
        second = compute_risk_score(signals)
        assert first == second


class TestClassifyRiskLevel:
    def test_zero_impact_is_low(self, settings: Settings) -> None:
        assert classify_risk_level(0.0, settings) is RiskLevel.LOW

    def test_low_risk_boundary(self, settings: Settings) -> None:
        assert classify_risk_level(24.9, settings) is RiskLevel.LOW

    def test_medium_risk_boundary(self, settings: Settings) -> None:
        assert classify_risk_level(25.0, settings) is RiskLevel.MEDIUM
        assert classify_risk_level(49.9, settings) is RiskLevel.MEDIUM

    def test_high_risk_boundary(self, settings: Settings) -> None:
        assert classify_risk_level(50.0, settings) is RiskLevel.HIGH
        assert classify_risk_level(74.9, settings) is RiskLevel.HIGH

    def test_critical_risk_boundary(self, settings: Settings) -> None:
        assert classify_risk_level(75.0, settings) is RiskLevel.CRITICAL
        assert classify_risk_level(100.0, settings) is RiskLevel.CRITICAL

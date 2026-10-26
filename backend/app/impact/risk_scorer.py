"""Deterministic, configurable structural risk scoring — see "Risk
scoring": "This is NOT probability of failure. It is a structural
change-impact risk heuristic."

The final score is exactly the sum of each signal's ``contribution``,
subject only to a documented 100.0 cap (see "The final score must equal
the sum of its contributions, subject only to a documented cap." and this
module's own tests for that invariant).
"""

from app.core.config import Settings
from app.domain.impact.enums import RiskLevel
from app.domain.impact.models import ImpactSignal

RISK_SCORE_CAP = 100.0


def compute_risk_score(signals: list[ImpactSignal]) -> float:
    """Sum of every signal's contribution, capped at ``RISK_SCORE_CAP``.

    Weights are configured to sum to 100 by default (see .env.example),
    so the cap is a defensive bound, not the normal operating case."""
    return min(sum(s.contribution for s in signals), RISK_SCORE_CAP)


def classify_risk_level(score: float, settings: Settings) -> RiskLevel:
    """Score -> RiskLevel via configurable thresholds — never a
    probability (see "Do not call these probabilities.")."""
    if score >= settings.impact_risk_critical_threshold:
        return RiskLevel.CRITICAL
    if score >= settings.impact_risk_high_threshold:
        return RiskLevel.HIGH
    if score >= settings.impact_risk_medium_threshold:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW

"""Deterministic heuristic intent classification — see the hybrid-
retrieval task's "Query intents" example list."""

from app.domain.rag.enums import QueryIntent
from app.rag.query_classifier import classify_intent


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


class TestExampleQuestions:
    def test_code_location(self) -> None:
        result = classify_intent(_normalize("Where is authentication implemented?"))
        assert result.primary_intent is QueryIntent.CODE_LOCATION

    def test_code_explanation(self) -> None:
        result = classify_intent(_normalize("Explain AuthService.login"))
        assert result.primary_intent is QueryIntent.CODE_EXPLANATION

    def test_caller_lookup(self) -> None:
        result = classify_intent(_normalize("Which functions call login()?"))
        assert result.primary_intent is QueryIntent.CALLER_LOOKUP

    def test_callee_lookup(self) -> None:
        result = classify_intent(_normalize("What does login() call?"))
        assert result.primary_intent is QueryIntent.CALLEE_LOOKUP

    def test_dependency_lookup(self) -> None:
        result = classify_intent(_normalize("What depends on UserRepository?"))
        assert result.primary_intent is QueryIntent.DEPENDENCY_LOOKUP

    def test_impact_analysis(self) -> None:
        result = classify_intent(_normalize("What happens if I change login()?"))
        assert result.primary_intent is QueryIntent.IMPACT_ANALYSIS

    def test_impact_analysis_changes_phrasing(self) -> None:
        # A rephrasing found during manual verification ("what happens"
        # vs. "what changes") that the original pattern missed.
        result = classify_intent(_normalize("What changes if login() is modified?"))
        assert result.primary_intent is QueryIntent.IMPACT_ANALYSIS

    def test_impact_analysis_may_be_affected_phrasing(self) -> None:
        # Found during the change-impact-analysis task's manual
        # verification — one of its own example questions ("Which API
        # endpoints may be affected?") originally fell through to UNKNOWN.
        result = classify_intent(_normalize("Which API endpoints may be affected?"))
        assert result.primary_intent is QueryIntent.IMPACT_ANALYSIS

    def test_impact_analysis_potentially_impacted_phrasing(self) -> None:
        result = classify_intent(_normalize("Which files are potentially impacted?"))
        assert result.primary_intent is QueryIntent.IMPACT_ANALYSIS

    def test_impact_analysis_how_risky_phrasing(self) -> None:
        result = classify_intent(_normalize("How risky is this change structurally?"))
        assert result.primary_intent is QueryIntent.IMPACT_ANALYSIS

    def test_architecture(self) -> None:
        result = classify_intent(_normalize("How is this repository structured?"))
        assert result.primary_intent is QueryIntent.ARCHITECTURE

    def test_api_lookup(self) -> None:
        result = classify_intent(_normalize("Which function handles POST /login?"))
        assert result.primary_intent is QueryIntent.API_LOOKUP

    def test_inheritance_lookup(self) -> None:
        result = classify_intent(_normalize("What classes extend BaseHandler?"))
        assert result.primary_intent is QueryIntent.INHERITANCE_LOOKUP


class TestFallbacks:
    def test_general_code_question(self) -> None:
        result = classify_intent(_normalize("Tell me about this function."))
        assert result.primary_intent is QueryIntent.GENERAL_CODE_QUESTION

    def test_unknown_question(self) -> None:
        result = classify_intent(_normalize("What is the weather like today?"))
        assert result.primary_intent is QueryIntent.UNKNOWN


class TestConfidenceAndSecondaryIntents:
    def test_matched_intents_have_higher_confidence_than_fallbacks(self) -> None:
        matched = classify_intent(_normalize("Where is authentication implemented?"))
        unknown = classify_intent(_normalize("What is the weather like today?"))
        assert matched.confidence > unknown.confidence

    def test_unmatched_rules_are_not_listed_as_secondary(self) -> None:
        result = classify_intent(_normalize("Where is authentication implemented?"))
        assert QueryIntent.DEPENDENCY_LOOKUP not in result.secondary_intents

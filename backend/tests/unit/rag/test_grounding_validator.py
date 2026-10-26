"""Deterministic abstention and confidence rules."""

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, SymbolMatchType
from app.domain.rag.enums import EvidenceSource, EvidenceType, QueryIntent, SymbolResolutionStatus
from app.domain.rag.models import (
    HybridRetrievalResult,
    QueryAnalysis,
    RankedEvidence,
    ResolvedSymbol,
    RetrievalDiagnostics,
    RetrievalEvidence,
    RetrievalPlan,
    ScoreComponents,
    SymbolResolution,
)
from app.rag.answer_models import AnswerConfidence, CodeCitation
from app.rag.grounding_validator import (
    check_post_generation,
    check_pre_generation,
    classify_confidence,
)


def _analysis(intent: QueryIntent, *, requires_exact_symbol_search: bool = True) -> QueryAnalysis:
    return QueryAnalysis(
        raw_question="q",
        normalized_question="q",
        primary_intent=intent,
        requires_exact_symbol_search=requires_exact_symbol_search,
    )


def _plan() -> RetrievalPlan:
    return RetrievalPlan(
        use_vector=True,
        use_graph=True,
        use_symbol_search=True,
        vector_top_k=8,
        graph_depth=1,
        symbol_limit=5,
    )


def _diagnostics() -> RetrievalDiagnostics:
    return RetrievalDiagnostics(
        retrieval_duration_ms=1, vector_duration_ms=1, graph_duration_ms=1, analysis_duration_ms=1
    )


def _ranked_evidence(score: float) -> RankedEvidence:
    evidence = RetrievalEvidence(
        id="e1",
        repository_id="repo-1",
        evidence_type=EvidenceType.CODE_CHUNK,
        symbol_id="sym-1",
        qualified_name="app.auth.login",
        file_path="app/auth.py",
        start_line=1,
        end_line=5,
        content="def login(): ...",
        source=EvidenceSource.VECTOR,
    )
    return RankedEvidence(
        evidence=evidence,
        hybrid_score=score,
        score_components=ScoreComponents(vector=score, exact=0.0, graph=0.0, intent=0.0),
        sources=[EvidenceSource.VECTOR],
    )


def _result(
    *, evidence=None, resolved_symbols=None, intent=QueryIntent.CODE_EXPLANATION
) -> HybridRetrievalResult:
    evidence = evidence or []
    resolved_symbols = resolved_symbols or []
    return HybridRetrievalResult(
        repository_id="repo-1",
        question="q",
        analysis=_analysis(intent),
        plan=_plan(),
        resolved_symbols=resolved_symbols,
        evidence=evidence,
        total_vector_candidates=len(evidence),
        total_graph_candidates=0,
        total_symbol_candidates=0,
        deduplicated_count=len(evidence),
        returned_count=len(evidence),
        truncated=False,
        diagnostics=_diagnostics(),
    )


def _resolved(name: str, *, status: SymbolResolutionStatus, candidates=None) -> SymbolResolution:
    candidates = candidates or []
    resolved_symbol = None
    if status in (SymbolResolutionStatus.EXACT, SymbolResolutionStatus.UNIQUE):
        resolved_symbol = ResolvedSymbol(
            symbol_id="sym-1",
            symbol_type=NodeLabel.FUNCTION,
            name=name,
            qualified_name=f"app.auth.{name}",
            file_path="app/auth.py",
            start_line=1,
            end_line=5,
            match_type=SymbolMatchType.EXACT_NAME,
            confidence=0.9,
        )
    return SymbolResolution(
        query=name, resolved_symbol=resolved_symbol, candidates=candidates, status=status
    )


def _settings(**overrides) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class TestPreGenerationNoEvidence:
    def test_abstains_with_no_evidence(self) -> None:
        decision = check_pre_generation(_result(evidence=[]), settings=_settings())
        assert decision.should_abstain is True
        assert decision.reason == "no_retrieval_evidence"


class TestPreGenerationUnresolvedSymbol:
    def test_abstains_when_all_resolutions_not_found_and_no_evidence(self) -> None:
        result = _result(
            evidence=[],
            resolved_symbols=[_resolved("login", status=SymbolResolutionStatus.NOT_FOUND)],
        )
        decision = check_pre_generation(result, settings=_settings())
        assert decision.should_abstain is True
        assert decision.reason == "target_symbol_unresolved"
        assert "login" in (decision.message or "")


class TestPreGenerationAmbiguousSymbol:
    def test_abstains_with_candidate_list_message(self) -> None:
        from app.domain.rag.models import ResolvedSymbol as RS

        candidates = [
            RS(
                symbol_id="s1",
                symbol_type=NodeLabel.FUNCTION,
                name="login",
                qualified_name="app.auth.service.login",
                file_path="a.py",
                start_line=1,
                end_line=2,
                match_type=SymbolMatchType.CONTAINS,
                confidence=0.4,
            ),
            RS(
                symbol_id="s2",
                symbol_type=NodeLabel.FUNCTION,
                name="login",
                qualified_name="tests.helpers.login",
                file_path="b.py",
                start_line=1,
                end_line=2,
                match_type=SymbolMatchType.CONTAINS,
                confidence=0.4,
            ),
        ]
        resolution = SymbolResolution(
            query="login",
            resolved_symbol=None,
            candidates=candidates,
            status=SymbolResolutionStatus.AMBIGUOUS,
        )
        result = _result(evidence=[_ranked_evidence(0.9)], resolved_symbols=[resolution])

        decision = check_pre_generation(result, settings=_settings())

        assert decision.should_abstain is True
        assert decision.reason == "ambiguous_symbol"
        assert "app.auth.service.login" in (decision.message or "")
        assert "tests.helpers.login" in (decision.message or "")
        assert "ambiguous" in (decision.message or "").lower()

    def test_does_not_abstain_if_an_exact_match_also_exists(self) -> None:
        result = _result(
            evidence=[_ranked_evidence(0.9)],
            resolved_symbols=[
                _resolved("login", status=SymbolResolutionStatus.EXACT),
                _resolved("helper", status=SymbolResolutionStatus.AMBIGUOUS),
            ],
        )
        decision = check_pre_generation(result, settings=_settings())
        assert decision.should_abstain is False


class TestPreGenerationLowRelevance:
    def test_abstains_below_configured_threshold(self) -> None:
        result = _result(evidence=[_ranked_evidence(0.05)])
        decision = check_pre_generation(
            result, settings=_settings(answer_min_evidence_relevance=0.15)
        )
        assert decision.should_abstain is True
        assert decision.reason == "evidence_below_relevance_threshold"

    def test_proceeds_above_threshold(self) -> None:
        result = _result(evidence=[_ranked_evidence(0.9)])
        decision = check_pre_generation(
            result, settings=_settings(answer_min_evidence_relevance=0.15)
        )
        assert decision.should_abstain is False


class TestPostGeneration:
    def test_abstains_when_llm_reports_insufficient_evidence(self) -> None:
        decision = check_post_generation(
            sufficient_evidence=False, had_citation_markers=True, citations=[]
        )
        assert decision.should_abstain is True
        assert decision.reason == "llm_reported_insufficient_evidence"

    def test_abstains_when_all_citation_attempts_are_invalid(self) -> None:
        decision = check_post_generation(
            sufficient_evidence=True, had_citation_markers=True, citations=[]
        )
        assert decision.should_abstain is True
        assert decision.reason == "citation_validation_failed"

    def test_proceeds_with_valid_citations(self) -> None:
        citation = CodeCitation(
            citation_id="1",
            file_path="a.py",
            start_line=1,
            end_line=2,
            symbol_id="s1",
            qualified_name="a.f",
            evidence_type=EvidenceType.CODE_CHUNK,
        )
        decision = check_post_generation(
            sufficient_evidence=True, had_citation_markers=True, citations=[citation]
        )
        assert decision.should_abstain is False

    def test_proceeds_when_no_citation_was_attempted_at_all(self) -> None:
        decision = check_post_generation(
            sufficient_evidence=True, had_citation_markers=False, citations=[]
        )
        assert decision.should_abstain is False


class TestClassifyConfidence:
    def test_high_confidence_with_exact_resolution_and_strong_evidence(self) -> None:
        citation = CodeCitation(
            citation_id="1",
            file_path="a.py",
            start_line=1,
            end_line=2,
            symbol_id="s1",
            qualified_name="a.f",
            evidence_type=EvidenceType.CODE_CHUNK,
        )
        level, reason = classify_confidence(
            resolved_symbols=[_resolved("login", status=SymbolResolutionStatus.EXACT)],
            citations=[citation],
            top_evidence_score=0.9,
            settings=_settings(),
        )
        assert level is AnswerConfidence.HIGH
        assert reason

    def test_low_confidence_with_no_citations(self) -> None:
        level, _reason = classify_confidence(
            resolved_symbols=[], citations=[], top_evidence_score=0.9, settings=_settings()
        )
        assert level is AnswerConfidence.LOW

    def test_medium_confidence_for_moderate_evidence(self) -> None:
        citation = CodeCitation(
            citation_id="1",
            file_path="a.py",
            start_line=1,
            end_line=2,
            symbol_id="s1",
            qualified_name="a.f",
            evidence_type=EvidenceType.CODE_CHUNK,
        )
        settings = _settings(
            answer_high_confidence_threshold=0.8, answer_medium_confidence_threshold=0.4
        )
        level, _reason = classify_confidence(
            resolved_symbols=[], citations=[citation], top_evidence_score=0.5, settings=settings
        )
        assert level is AnswerConfidence.MEDIUM

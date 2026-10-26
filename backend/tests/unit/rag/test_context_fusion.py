"""Context-fusion ranking — score calculation, exact-match boosting,
graph proximity scoring, intent relevance, stable ordering."""

from app.core.config import Settings
from app.domain.rag.enums import EvidenceSource, EvidenceType, QueryIntent
from app.domain.rag.models import RetrievalEvidence
from app.rag.context_fusion import rank_evidence
from app.rag.evidence import DeduplicatedEvidence


def _dedup(
    id_: str,
    *,
    sources: list[EvidenceSource],
    vector_score: float | None = None,
    graph_distance: int | None = None,
    exact_match_score: float | None = None,
    evidence_type: EvidenceType = EvidenceType.CODE_CHUNK,
    relationship_type: str | None = None,
    metadata: dict[str, object] | None = None,
    symbol_id: str | None = "sym-1",
) -> DeduplicatedEvidence:
    evidence = RetrievalEvidence(
        id=id_,
        repository_id="repo-1",
        evidence_type=evidence_type,
        symbol_id=symbol_id,
        qualified_name="app.auth.login",
        file_path="app/auth.py",
        start_line=1,
        end_line=5,
        content="content",
        source=sources[0],
        relationship_type=relationship_type,
        metadata=metadata or {},
    )
    return DeduplicatedEvidence(
        evidence=evidence,
        sources=sources,
        vector_score=vector_score,
        graph_distance=graph_distance,
        exact_match_score=exact_match_score,
    )


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


class TestScoreCalculation:
    def test_hybrid_score_is_the_weighted_sum_of_components(self) -> None:
        settings = _settings()
        item = _dedup(
            "v1",
            sources=[EvidenceSource.VECTOR],
            vector_score=1.0,
            exact_match_score=0.0,
            graph_distance=None,
        )
        ranked = rank_evidence(
            [item], analysis_intent=QueryIntent.UNKNOWN, resolved_symbols=[], settings=settings
        )
        expected = settings.hybrid_vector_weight * 1.0 + settings.hybrid_intent_weight * 0.5
        assert ranked[0].hybrid_score == expected

    def test_score_components_are_returned_for_debugging(self) -> None:
        item = _dedup("v1", sources=[EvidenceSource.VECTOR], vector_score=0.6)
        ranked = rank_evidence(
            [item], analysis_intent=QueryIntent.UNKNOWN, resolved_symbols=[], settings=_settings()
        )
        assert ranked[0].score_components.vector == 0.6


class TestExactMatchBoosting:
    def test_higher_exact_match_score_yields_higher_hybrid_score(self) -> None:
        low = _dedup("a", sources=[EvidenceSource.SYMBOL], exact_match_score=0.2)
        high = _dedup("b", sources=[EvidenceSource.SYMBOL], exact_match_score=1.0)
        ranked = rank_evidence(
            [low, high],
            analysis_intent=QueryIntent.UNKNOWN,
            resolved_symbols=[],
            settings=_settings(),
        )
        assert ranked[0].evidence.id == "b"


class TestGraphProximityScoring:
    def test_closer_evidence_scores_higher(self) -> None:
        far = _dedup("a", sources=[EvidenceSource.GRAPH], graph_distance=3)
        near = _dedup("b", sources=[EvidenceSource.GRAPH], graph_distance=1)
        ranked = rank_evidence(
            [far, near],
            analysis_intent=QueryIntent.UNKNOWN,
            resolved_symbols=[],
            settings=_settings(),
        )
        assert ranked[0].evidence.id == "b"

    def test_unknown_distance_scores_zero_graph_component(self) -> None:
        item = _dedup("a", sources=[EvidenceSource.GRAPH], graph_distance=None)
        ranked = rank_evidence(
            [item], analysis_intent=QueryIntent.UNKNOWN, resolved_symbols=[], settings=_settings()
        )
        assert ranked[0].score_components.graph == 0.0


class TestIntentRelevance:
    def test_caller_lookup_favors_caller_operation_call_edges(self) -> None:
        matching = _dedup(
            "a",
            sources=[EvidenceSource.GRAPH],
            relationship_type="CALLS",
            metadata={"graph_operation": "callers"},
        )
        other = _dedup(
            "b",
            sources=[EvidenceSource.GRAPH],
            relationship_type="IMPORTS",
            metadata={"graph_operation": "dependencies"},
        )
        ranked = rank_evidence(
            [other, matching],
            analysis_intent=QueryIntent.CALLER_LOOKUP,
            resolved_symbols=[],
            settings=_settings(),
        )
        assert ranked[0].evidence.id == "a"
        assert ranked[0].score_components.intent == 1.0

    def test_architecture_favors_module_and_statistics_evidence(self) -> None:
        module_evidence = _dedup(
            "a", sources=[EvidenceSource.GRAPH], evidence_type=EvidenceType.MODULE
        )
        code_chunk = _dedup(
            "b", sources=[EvidenceSource.VECTOR], evidence_type=EvidenceType.CODE_CHUNK
        )
        ranked = rank_evidence(
            [code_chunk, module_evidence],
            analysis_intent=QueryIntent.ARCHITECTURE,
            resolved_symbols=[],
            settings=_settings(),
        )
        assert ranked[0].evidence.id == "a"


class TestStableOrdering:
    def test_results_are_sorted_by_hybrid_score_descending(self) -> None:
        low = _dedup("low", sources=[EvidenceSource.VECTOR], vector_score=0.1)
        high = _dedup("high", sources=[EvidenceSource.VECTOR], vector_score=0.9)
        mid = _dedup("mid", sources=[EvidenceSource.VECTOR], vector_score=0.5)
        ranked = rank_evidence(
            [low, high, mid],
            analysis_intent=QueryIntent.UNKNOWN,
            resolved_symbols=[],
            settings=_settings(),
        )
        assert [r.evidence.id for r in ranked] == ["high", "mid", "low"]

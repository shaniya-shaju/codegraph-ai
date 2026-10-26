"""Context budgeting — character limit, evidence-count limit, per-file
diversity, graph/vector balance, truncation flag, exact-match
preservation, citation metadata never split from content."""

from app.core.config import Settings
from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.rag.models import RankedEvidence, RetrievalEvidence, ScoreComponents
from app.rag.context_budget import apply_budget


def _ranked(
    id_: str,
    *,
    score: float,
    sources: list[EvidenceSource],
    file_path: str = "a.py",
    content_length: int = 10,
) -> RankedEvidence:
    evidence = RetrievalEvidence(
        id=id_,
        repository_id="repo-1",
        evidence_type=EvidenceType.CODE_CHUNK,
        symbol_id=id_,
        qualified_name=None,
        file_path=file_path,
        start_line=1,
        end_line=5,
        content="x" * content_length,
        source=sources[0],
    )
    return RankedEvidence(
        evidence=evidence,
        hybrid_score=score,
        score_components=ScoreComponents(vector=score, exact=0.0, graph=0.0, intent=0.0),
        sources=sources,
    )


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[call-arg]


class TestCharacterLimit:
    def test_stops_once_the_character_budget_is_exceeded(self) -> None:
        items = [
            _ranked(
                f"i{i}",
                score=1.0 - i * 0.01,
                sources=[EvidenceSource.VECTOR],
                file_path=f"f{i}.py",
                content_length=100,
            )
            for i in range(5)
        ]
        settings = _settings(
            rag_max_context_characters=250, rag_max_evidence_per_file=10, rag_max_vector_evidence=10
        )
        selected, truncated = apply_budget(items, settings=settings)
        assert len(selected) == 2
        assert truncated is True

    def test_highest_ranked_items_are_kept_first(self) -> None:
        items = [
            _ranked(
                f"i{i}",
                score=1.0 - i * 0.1,
                sources=[EvidenceSource.VECTOR],
                file_path=f"f{i}.py",
                content_length=100,
            )
            for i in range(5)
        ]
        settings = _settings(
            rag_max_context_characters=250, rag_max_evidence_per_file=10, rag_max_vector_evidence=10
        )
        selected, _ = apply_budget(items, settings=settings)
        assert [s.evidence.id for s in selected] == ["i0", "i1"]


class TestEvidenceCountLimit:
    def test_stops_once_the_item_count_is_reached(self) -> None:
        items = [
            _ranked(f"i{i}", score=1.0, sources=[EvidenceSource.VECTOR], file_path=f"f{i}.py")
            for i in range(10)
        ]
        settings = _settings(
            rag_max_evidence_items=3,
            rag_max_evidence_per_file=10,
            rag_max_vector_evidence=10,
            rag_max_context_characters=100000,
        )
        selected, truncated = apply_budget(items, settings=settings)
        assert len(selected) == 3
        assert truncated is True


class TestPerFileDiversity:
    def test_a_single_file_cannot_monopolize_the_context(self) -> None:
        items = [
            _ranked(
                f"i{i}", score=1.0 - i * 0.01, sources=[EvidenceSource.VECTOR], file_path="same.py"
            )
            for i in range(5)
        ]
        items.append(
            _ranked("other", score=0.1, sources=[EvidenceSource.VECTOR], file_path="other.py")
        )
        settings = _settings(
            rag_max_evidence_per_file=2,
            rag_max_evidence_items=100,
            rag_max_context_characters=100000,
            rag_max_vector_evidence=100,
        )
        selected, truncated = apply_budget(items, settings=settings)
        same_file_count = sum(1 for s in selected if s.evidence.file_path == "same.py")
        assert same_file_count == 2
        assert any(s.evidence.file_path == "other.py" for s in selected)
        assert truncated is True


class TestGraphVectorBalance:
    def test_vector_evidence_is_capped_independently_of_graph(self) -> None:
        vector_items = [
            _ranked(f"v{i}", score=1.0, sources=[EvidenceSource.VECTOR], file_path=f"v{i}.py")
            for i in range(5)
        ]
        graph_items = [
            _ranked(f"g{i}", score=0.9, sources=[EvidenceSource.GRAPH], file_path=f"g{i}.py")
            for i in range(5)
        ]
        settings = _settings(
            rag_max_vector_evidence=2,
            rag_max_graph_evidence=2,
            rag_max_evidence_items=100,
            rag_max_context_characters=100000,
            rag_max_evidence_per_file=100,
        )
        selected, _ = apply_budget(vector_items + graph_items, settings=settings)
        vector_count = sum(1 for s in selected if EvidenceSource.VECTOR in s.sources)
        graph_count = sum(1 for s in selected if EvidenceSource.GRAPH in s.sources)
        assert vector_count == 2
        assert graph_count == 2


class TestTruncationFlag:
    def test_false_when_everything_fits(self) -> None:
        items = [_ranked("i1", score=1.0, sources=[EvidenceSource.VECTOR])]
        settings = _settings()
        _, truncated = apply_budget(items, settings=settings)
        assert truncated is False


class TestExactMatchPreservation:
    def test_a_high_scoring_exact_match_survives_a_tight_item_budget(self) -> None:
        exact = _ranked("exact", score=1.0, sources=[EvidenceSource.SYMBOL], file_path="exact.py")
        noise = [
            _ranked(f"n{i}", score=0.1, sources=[EvidenceSource.VECTOR], file_path=f"n{i}.py")
            for i in range(10)
        ]
        settings = _settings(
            rag_max_evidence_items=1,
            rag_max_context_characters=100000,
            rag_max_evidence_per_file=10,
            rag_max_vector_evidence=10,
        )
        selected, _ = apply_budget([exact, *noise], settings=settings)
        assert selected == [exact]


class TestCitationMetadataNeverSplit:
    def test_included_items_always_carry_their_full_location(self) -> None:
        items = [_ranked("i1", score=1.0, sources=[EvidenceSource.VECTOR], file_path="a.py")]
        selected, _ = apply_budget(items, settings=_settings())
        assert selected[0].evidence.file_path == "a.py"
        assert selected[0].evidence.start_line == 1
        assert selected[0].evidence.end_line == 5
        assert selected[0].evidence.content  # content present alongside citation

"""Citation validation — do not trust citations invented by the LLM;
every surviving citation must map to real evidence-pool metadata."""

from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.rag.models import RetrievalEvidence
from app.rag.citation_builder import EvidencePoolItem
from app.rag.citation_validator import validate_and_build_citations


def _pool_item(
    evidence_id: str, *, file_path: str = "app/auth.py", score: float = 0.5
) -> EvidencePoolItem:
    evidence = RetrievalEvidence(
        id=f"internal-{evidence_id}",
        repository_id="repo-1",
        evidence_type=EvidenceType.CODE_CHUNK,
        symbol_id="sym-1",
        qualified_name="app.auth.login",
        file_path=file_path,
        start_line=10,
        end_line=20,
        content="def login(): ...",
        source=EvidenceSource.VECTOR,
    )
    return EvidencePoolItem(evidence_id=evidence_id, evidence=evidence, hybrid_score=score)


class TestCorrectCitations:
    def test_valid_markers_become_citations(self) -> None:
        pool = [_pool_item("E1"), _pool_item("E2", file_path="app/db.py")]
        result = validate_and_build_citations("Login is here [E1] and uses [E2].", pool)

        assert len(result.citations) == 2
        assert result.citations[0].file_path == "app/auth.py"
        assert result.citations[1].file_path == "app/db.py"
        assert result.invalid_ids == []

    def test_markers_are_renumbered_in_order_of_first_appearance(self) -> None:
        pool = [_pool_item("E1"), _pool_item("E2")]
        result = validate_and_build_citations("See [E2] first, then [E1].", pool)

        assert "[1]" in result.answer_text
        assert "[2]" in result.answer_text
        assert result.answer_text.index("[1]") < result.answer_text.index("[2]")
        assert result.citations[0].citation_id == "1"
        assert result.citations[1].citation_id == "2"

    def test_repeated_marker_produces_one_citation(self) -> None:
        pool = [_pool_item("E1")]
        result = validate_and_build_citations("Login [E1] does X. It also does Y [E1].", pool)
        assert len(result.citations) == 1


class TestInvalidLlmCitation:
    def test_unknown_id_is_stripped_and_recorded(self) -> None:
        pool = [_pool_item("E1")]
        result = validate_and_build_citations("Login is here [E1] and also [E99].", pool)

        assert result.invalid_ids == ["E99"]
        assert "[E99]" not in result.answer_text
        assert len(result.citations) == 1

    def test_all_markers_invalid_yields_no_citations(self) -> None:
        pool = [_pool_item("E1")]
        result = validate_and_build_citations("This claims [E7] and [E8].", pool)

        assert result.citations == []
        assert set(result.invalid_ids) == {"E7", "E8"}


class TestNeverTrustsLlmAuthoredMetadata:
    def test_citation_fields_always_come_from_the_pool_not_the_text(self) -> None:
        pool = [_pool_item("E1", file_path="app/auth.py")]
        # The answer text mentions a completely different, invented file path
        # as prose — this must never leak into the citation's file_path.
        result = validate_and_build_citations(
            "See fake/invented/nonexistent.py:999-999 for details [E1].", pool
        )
        assert result.citations[0].file_path == "app/auth.py"
        assert result.citations[0].start_line == 10
        assert result.citations[0].end_line == 20


class TestUncitedHighRelevanceDetection:
    def test_flags_high_relevance_evidence_that_was_never_cited(self) -> None:
        pool = [_pool_item("E1", score=0.9), _pool_item("E2", score=0.1)]
        result = validate_and_build_citations(
            "Nothing cited here.", pool, high_relevance_threshold=0.5
        )
        assert "E1" in result.uncited_high_relevance_ids
        assert "E2" not in result.uncited_high_relevance_ids

    def test_no_flag_when_high_relevance_evidence_is_cited(self) -> None:
        pool = [_pool_item("E1", score=0.9)]
        result = validate_and_build_citations("Cited [E1].", pool, high_relevance_threshold=0.5)
        assert result.uncited_high_relevance_ids == []


class TestEmptyAnswer:
    def test_no_markers_produces_no_citations(self) -> None:
        pool = [_pool_item("E1")]
        result = validate_and_build_citations("A plain answer with no markers.", pool)
        assert result.citations == []
        assert result.invalid_ids == []

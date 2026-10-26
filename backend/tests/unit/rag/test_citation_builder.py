"""Evidence-pool construction — assigns closed, sequential ``E<n>`` ids
and formats the prompt-ready evidence block."""

from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.rag.models import RankedEvidence, RetrievalEvidence, ScoreComponents
from app.rag.citation_builder import build_evidence_pool, evidence_pool_index, format_evidence_block


def _ranked(id_: str, *, content: str = "def f(): pass", score: float = 0.5) -> RankedEvidence:
    evidence = RetrievalEvidence(
        id=id_,
        repository_id="repo-1",
        evidence_type=EvidenceType.CODE_CHUNK,
        symbol_id="sym-1",
        qualified_name="app.auth.login",
        file_path="app/auth.py",
        start_line=1,
        end_line=5,
        content=content,
        source=EvidenceSource.VECTOR,
    )
    return RankedEvidence(
        evidence=evidence,
        hybrid_score=score,
        score_components=ScoreComponents(vector=score, exact=0.0, graph=0.0, intent=0.0),
        sources=[EvidenceSource.VECTOR],
    )


class TestBuildEvidencePool:
    def test_assigns_sequential_ids_in_rank_order(self) -> None:
        pool = build_evidence_pool([_ranked("a"), _ranked("b"), _ranked("c")], max_items=10)
        assert [item.evidence_id for item in pool] == ["E1", "E2", "E3"]
        assert [item.evidence.id for item in pool] == ["a", "b", "c"]

    def test_bounded_by_max_items(self) -> None:
        pool = build_evidence_pool([_ranked(str(i)) for i in range(10)], max_items=3)
        assert len(pool) == 3

    def test_empty_evidence_produces_empty_pool(self) -> None:
        assert build_evidence_pool([], max_items=10) == []


class TestEvidencePoolIndex:
    def test_looks_up_by_evidence_id(self) -> None:
        pool = build_evidence_pool([_ranked("a")], max_items=10)
        index = evidence_pool_index(pool)
        assert index["E1"].evidence.id == "a"


class TestFormatEvidenceBlock:
    def test_includes_id_location_and_content(self) -> None:
        pool = build_evidence_pool([_ranked("a", content="def login(): return True")], max_items=10)
        block = format_evidence_block(pool)
        assert "[E1]" in block
        assert "app/auth.py:1-5" in block
        assert "app.auth.login" in block
        assert "def login(): return True" in block

    def test_empty_pool_says_no_evidence(self) -> None:
        block = format_evidence_block([])
        assert "no evidence" in block.lower()

    def test_long_content_is_truncated(self) -> None:
        pool = build_evidence_pool([_ranked("a", content="x" * 5000)], max_items=10)
        block = format_evidence_block(pool, max_content_characters=100)
        assert "truncated" in block
        assert len(block) < 5000

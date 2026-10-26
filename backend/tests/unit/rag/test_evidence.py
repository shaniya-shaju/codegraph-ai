"""Evidence deduplication — see "Evidence deduplication": merge same-
symbol vector+graph hits, preserve provenance, never triple-send the
same source."""

from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.rag.models import RetrievalEvidence
from app.rag.evidence import deduplicate_evidence


def _evidence(
    id_: str,
    *,
    source: EvidenceSource,
    symbol_id: str | None = "sym-1",
    file_path: str | None = "app/auth.py",
    start_line: int | None = 1,
    end_line: int | None = 5,
    content: str = "content",
    vector_score: float | None = None,
    graph_distance: int | None = None,
    exact_match_score: float | None = None,
) -> RetrievalEvidence:
    return RetrievalEvidence(
        id=id_,
        repository_id="repo-1",
        evidence_type=EvidenceType.CODE_CHUNK,
        symbol_id=symbol_id,
        qualified_name="app.auth.login",
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        content=content,
        source=source,
        vector_score=vector_score,
        graph_distance=graph_distance,
        exact_match_score=exact_match_score,
    )


class TestVectorOnlyEvidence:
    def test_passes_through_unmerged(self) -> None:
        result = deduplicate_evidence(
            [_evidence("v1", source=EvidenceSource.VECTOR, vector_score=0.7)]
        )
        assert len(result) == 1
        assert result[0].sources == [EvidenceSource.VECTOR]
        assert result[0].vector_score == 0.7


class TestGraphOnlyEvidence:
    def test_passes_through_unmerged(self) -> None:
        result = deduplicate_evidence(
            [_evidence("g1", source=EvidenceSource.GRAPH, graph_distance=1)]
        )
        assert len(result) == 1
        assert result[0].sources == [EvidenceSource.GRAPH]
        assert result[0].graph_distance == 1


class TestSameSymbolFromBothSources:
    def test_merges_into_one_item(self) -> None:
        items = [
            _evidence(
                "v1",
                source=EvidenceSource.VECTOR,
                vector_score=0.7,
                content="full source code here",
            ),
            _evidence("g1", source=EvidenceSource.GRAPH, graph_distance=1, content="short summary"),
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 1
        assert set(result[0].sources) == {EvidenceSource.VECTOR, EvidenceSource.GRAPH}
        assert result[0].vector_score == 0.7
        assert result[0].graph_distance == 1

    def test_representative_content_prefers_vector_over_graph(self) -> None:
        items = [
            _evidence("g1", source=EvidenceSource.GRAPH, content="short summary"),
            _evidence("v1", source=EvidenceSource.VECTOR, content="full source code here"),
        ]
        result = deduplicate_evidence(items)
        assert result[0].evidence.content == "full source code here"


class TestDuplicateElimination:
    def test_three_hits_for_the_same_symbol_become_one_item(self) -> None:
        items = [
            _evidence("v1", source=EvidenceSource.VECTOR, vector_score=0.9),
            _evidence("g1", source=EvidenceSource.GRAPH, graph_distance=1),
            _evidence("s1", source=EvidenceSource.SYMBOL, exact_match_score=1.0),
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 1
        assert len(result[0].sources) == 3

    def test_distinct_symbols_are_not_merged(self) -> None:
        items = [
            _evidence("v1", source=EvidenceSource.VECTOR, symbol_id="sym-1"),
            _evidence("v2", source=EvidenceSource.VECTOR, symbol_id="sym-2"),
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 2


class TestScoreAggregation:
    def test_takes_the_strongest_score_from_each_channel(self) -> None:
        items = [
            _evidence("v1", source=EvidenceSource.VECTOR, vector_score=0.5),
            _evidence("v2", source=EvidenceSource.VECTOR, vector_score=0.9),
        ]
        result = deduplicate_evidence(items)
        assert result[0].vector_score == 0.9

    def test_takes_the_closest_graph_distance(self) -> None:
        items = [
            _evidence("g1", source=EvidenceSource.GRAPH, graph_distance=3),
            _evidence("g2", source=EvidenceSource.GRAPH, graph_distance=1),
        ]
        result = deduplicate_evidence(items)
        assert result[0].graph_distance == 1


class TestLocationBasedMergeWithoutSymbolId:
    def test_same_file_and_line_range_merges_when_no_symbol_id(self) -> None:
        items = [
            _evidence(
                "v1",
                source=EvidenceSource.VECTOR,
                symbol_id=None,
                file_path="a.py",
                start_line=1,
                end_line=10,
            ),
            _evidence(
                "g1",
                source=EvidenceSource.GRAPH,
                symbol_id=None,
                file_path="a.py",
                start_line=1,
                end_line=10,
            ),
        ]
        result = deduplicate_evidence(items)
        assert len(result) == 1

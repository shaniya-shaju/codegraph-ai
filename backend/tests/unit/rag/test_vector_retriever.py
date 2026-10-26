"""Vector retriever adapter — mocks app.indexing.retrieval_service.search
entirely (see "Vector adapter": "Mock the existing retrieval service.
Verify metadata preservation.")."""

from app.domain.rag.enums import EvidenceSource, EvidenceType
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import VectorSearchResult
from app.rag.vector_retriever import VectorRetriever


def _result(
    chunk_id: str = "c1",
    *,
    chunk_type: ChunkType = ChunkType.FUNCTION,
    qualified_name: str = "app.auth.login",
    file_path: str = "app/auth.py",
    start_line: int = 10,
    end_line: int = 20,
    score: float = 0.8,
) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        repository_id="repo-1",
        symbol_id="sym-1",
        chunk_type=chunk_type,
        qualified_name=qualified_name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        content="def login(): ...",
        score=score,
        distance=1 - score,
    )


class _FakeSearchFn:
    def __init__(self, results: list[VectorSearchResult]) -> None:
        self._results = results
        self.calls: list[dict[str, object]] = []

    def __call__(self, embedding_provider, vector_store, settings, query):
        self.calls.append(
            {
                "repository_id": query.repository_id,
                "query": query.query,
                "top_k": query.top_k,
                "chunk_types": query.chunk_types,
                "file_paths": query.file_paths,
            }
        )
        return self._results


class TestMetadataPreservation:
    def test_chunk_fields_carry_through_to_evidence(self) -> None:
        fake = _FakeSearchFn([_result()])
        retriever = VectorRetriever(None, None, None, search_fn=fake)  # type: ignore[arg-type]

        evidence = retriever.run(repository_id="repo-1", query="how does login work", top_k=5)

        assert len(evidence) == 1
        item = evidence[0]
        assert item.symbol_id == "sym-1"
        assert item.qualified_name == "app.auth.login"
        assert item.file_path == "app/auth.py"
        assert item.start_line == 10
        assert item.end_line == 20
        assert item.vector_score == 0.8
        assert item.source is EvidenceSource.VECTOR
        assert item.metadata["chunk_id"] == "c1"


class TestEvidenceTypeMapping:
    def test_module_chunk_maps_to_module_evidence_type(self) -> None:
        fake = _FakeSearchFn([_result(chunk_type=ChunkType.MODULE)])
        retriever = VectorRetriever(None, None, None, search_fn=fake)  # type: ignore[arg-type]
        evidence = retriever.run(repository_id="repo-1", query="q", top_k=5)
        assert evidence[0].evidence_type is EvidenceType.MODULE

    def test_api_endpoint_chunk_maps_to_api_endpoint_evidence_type(self) -> None:
        fake = _FakeSearchFn([_result(chunk_type=ChunkType.API_ENDPOINT)])
        retriever = VectorRetriever(None, None, None, search_fn=fake)  # type: ignore[arg-type]
        evidence = retriever.run(repository_id="repo-1", query="q", top_k=5)
        assert evidence[0].evidence_type is EvidenceType.API_ENDPOINT

    def test_function_chunk_maps_to_code_chunk_evidence_type(self) -> None:
        fake = _FakeSearchFn([_result(chunk_type=ChunkType.FUNCTION)])
        retriever = VectorRetriever(None, None, None, search_fn=fake)  # type: ignore[arg-type]
        evidence = retriever.run(repository_id="repo-1", query="q", top_k=5)
        assert evidence[0].evidence_type is EvidenceType.CODE_CHUNK


class TestQueryConstruction:
    def test_top_k_and_filters_are_forwarded(self) -> None:
        fake = _FakeSearchFn([])
        retriever = VectorRetriever(None, None, None, search_fn=fake)  # type: ignore[arg-type]

        retriever.run(
            repository_id="repo-1",
            query="q",
            top_k=7,
            chunk_types=[ChunkType.FUNCTION],
            file_paths=["a.py"],
        )

        assert fake.calls[0]["top_k"] == 7
        assert fake.calls[0]["chunk_types"] == [ChunkType.FUNCTION]
        assert fake.calls[0]["file_paths"] == ["a.py"]

    def test_no_results_returns_empty_list(self) -> None:
        fake = _FakeSearchFn([])
        retriever = VectorRetriever(None, None, None, search_fn=fake)  # type: ignore[arg-type]
        assert retriever.run(repository_id="repo-1", query="q", top_k=5) == []

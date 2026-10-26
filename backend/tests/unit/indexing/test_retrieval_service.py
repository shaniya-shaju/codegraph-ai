"""Retrieval service: validation, repository scoping, filter building,
score conversion, ordering, minimum-score filtering, citation metadata,
and fragment deduplication.

The vector store itself is faked (records the search call and returns
pre-set matches) so these tests isolate retrieval_service's own logic
from ChromaDB (already covered separately in test_chroma_store.py).
"""

import pytest

from app.core.config import Settings
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import VectorSearchQuery
from app.indexing.exceptions import InvalidQueryError
from app.indexing.retrieval_service import search
from app.indexing.vector_store import VectorStoreMatch
from tests.fakes import FakeEmbeddingProvider


class _FakeVectorStore:
    def __init__(self, matches: list[VectorStoreMatch]) -> None:
        self._matches = matches
        self.last_repository_id: str | None = None
        self.last_top_k: int | None = None
        self.last_where: dict[str, object] | None = None

    def upsert(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def delete(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def delete_repository(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def search(
        self,
        repository_id: str,
        query_embedding: list[float],
        *,
        top_k: int,
        where: dict[str, object] | None = None,
    ) -> list[VectorStoreMatch]:
        self.last_repository_id = repository_id
        self.last_top_k = top_k
        self.last_where = where
        return self._matches[:top_k]

    def count(self, repository_id: str) -> int:
        raise NotImplementedError

    def health_check(self) -> str:
        return "ok"


def _match(
    chunk_id: str,
    *,
    symbol_id: str | None = "sym-1",
    chunk_type: str = "function",
    file_path: str = "m.py",
    start_line: int = 1,
    end_line: int = 5,
    distance: float | None = 0.1,
    content: str = "def f(): pass",
    qualified_name: str | None = "m.f",
) -> VectorStoreMatch:
    return VectorStoreMatch(
        chunk_id=chunk_id,
        content=content,
        distance=distance,
        metadata={
            "symbol_id": symbol_id,
            "chunk_type": chunk_type,
            "qualified_name": qualified_name,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
        },
    )


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def _query(**overrides: object) -> VectorSearchQuery:
    base: dict[str, object] = {
        "repository_id": "repo-1",
        "query": "how does login work",
        "top_k": 5,
    }
    base.update(overrides)
    return VectorSearchQuery(**base)  # type: ignore[arg-type]


class TestQueryValidation:
    def test_empty_query_is_rejected(self) -> None:
        store = _FakeVectorStore([])
        with pytest.raises(InvalidQueryError):
            search(FakeEmbeddingProvider(), store, _settings(), _query(query=""))

    def test_whitespace_only_query_is_rejected(self) -> None:
        store = _FakeVectorStore([])
        with pytest.raises(InvalidQueryError):
            search(FakeEmbeddingProvider(), store, _settings(), _query(query="   "))

    def test_top_k_below_one_is_rejected(self) -> None:
        store = _FakeVectorStore([])
        with pytest.raises(InvalidQueryError):
            search(FakeEmbeddingProvider(), store, _settings(), _query(top_k=0))

    def test_top_k_above_configured_max_is_rejected(self) -> None:
        store = _FakeVectorStore([])
        settings = _settings(vector_max_top_k=10)
        with pytest.raises(InvalidQueryError):
            search(FakeEmbeddingProvider(), store, settings, _query(top_k=11))

    def test_top_k_at_configured_max_is_accepted(self) -> None:
        store = _FakeVectorStore([_match("a")])
        settings = _settings(vector_max_top_k=10)
        results = search(FakeEmbeddingProvider(), store, settings, _query(top_k=10))
        assert results  # did not raise


class TestRepositoryScoping:
    def test_repository_id_is_passed_through_to_the_store(self) -> None:
        store = _FakeVectorStore([])
        search(FakeEmbeddingProvider(), store, _settings(), _query(repository_id="repo-42"))
        assert store.last_repository_id == "repo-42"


class TestScoreConversion:
    def test_zero_distance_is_a_perfect_score(self) -> None:
        store = _FakeVectorStore([_match("a", distance=0.0)])
        results = search(FakeEmbeddingProvider(), store, _settings(), _query())
        assert results[0].score == 1.0

    def test_distance_of_one_is_zero_score(self) -> None:
        store = _FakeVectorStore([_match("a", distance=1.0)])
        results = search(FakeEmbeddingProvider(), store, _settings(), _query())
        assert results[0].score == 0.0

    def test_score_is_clamped_to_the_zero_one_range(self) -> None:
        store = _FakeVectorStore([_match("a", distance=1.8)])
        results = search(FakeEmbeddingProvider(), store, _settings(), _query())
        assert results[0].score == 0.0

    def test_missing_distance_defaults_to_zero_score(self) -> None:
        store = _FakeVectorStore([_match("a", distance=None)])
        results = search(FakeEmbeddingProvider(), store, _settings(), _query())
        assert results[0].score == 0.0
        assert results[0].distance is None


class TestMinimumScoreFiltering:
    def test_results_below_the_query_minimum_score_are_dropped(self) -> None:
        store = _FakeVectorStore([_match("high", distance=0.1), _match("low", distance=0.9)])
        results = search(
            FakeEmbeddingProvider(), store, _settings(), _query(minimum_score=0.5, top_k=10)
        )
        assert {r.chunk_id for r in results} == {"high"}

    def test_settings_floor_applies_when_query_does_not_specify_one(self) -> None:
        store = _FakeVectorStore([_match("high", distance=0.1), _match("low", distance=0.9)])
        settings = _settings(vector_min_score=0.5)
        results = search(FakeEmbeddingProvider(), store, settings, _query(top_k=10))
        assert {r.chunk_id for r in results} == {"high"}


class TestMetadataFiltering:
    def test_chunk_type_filter_is_translated_into_a_where_clause(self) -> None:
        store = _FakeVectorStore([])
        search(
            FakeEmbeddingProvider(), store, _settings(), _query(chunk_types=[ChunkType.FUNCTION])
        )
        assert store.last_where == {"chunk_type": "function"}

    def test_multiple_chunk_types_use_a_list(self) -> None:
        store = _FakeVectorStore([])
        search(
            FakeEmbeddingProvider(),
            store,
            _settings(),
            _query(chunk_types=[ChunkType.FUNCTION, ChunkType.METHOD]),
        )
        assert store.last_where is not None
        assert sorted(store.last_where["chunk_type"]) == ["function", "method"]  # type: ignore[index]

    def test_file_path_filter_is_translated_into_a_where_clause(self) -> None:
        store = _FakeVectorStore([])
        search(FakeEmbeddingProvider(), store, _settings(), _query(file_paths=["app/auth.py"]))
        assert store.last_where == {"file_path": "app/auth.py"}

    def test_qualified_name_prefix_filters_results_after_fetch(self) -> None:
        store = _FakeVectorStore(
            [
                _match("a", qualified_name="app.auth.login"),
                _match("b", qualified_name="app.other.f"),
            ]
        )
        results = search(
            FakeEmbeddingProvider(),
            store,
            _settings(),
            _query(qualified_name_prefix="app.auth", top_k=10),
        )
        assert {r.chunk_id for r in results} == {"a"}


class TestResultOrdering:
    def test_results_are_sorted_by_score_descending(self) -> None:
        store = _FakeVectorStore(
            [
                _match("low", symbol_id="s1", distance=0.8),
                _match("high", symbol_id="s2", distance=0.1),
            ]
        )
        results = search(FakeEmbeddingProvider(), store, _settings(), _query(top_k=10))
        assert [r.chunk_id for r in results] == ["high", "low"]


class TestCitationMetadataPreservation:
    def test_file_and_line_information_survives_into_the_result(self) -> None:
        store = _FakeVectorStore([_match("a", file_path="app/auth.py", start_line=10, end_line=20)])
        results = search(FakeEmbeddingProvider(), store, _settings(), _query())
        assert results[0].file_path == "app/auth.py"
        assert results[0].start_line == 10
        assert results[0].end_line == 20


class TestDuplicateResultReduction:
    def test_same_symbol_and_chunk_type_keeps_only_the_highest_score(self) -> None:
        store = _FakeVectorStore(
            [
                _match("fragment-1", symbol_id="s1", chunk_type="function", distance=0.5),
                _match("fragment-2", symbol_id="s1", chunk_type="function", distance=0.1),
            ]
        )
        results = search(FakeEmbeddingProvider(), store, _settings(), _query(top_k=10))
        assert len(results) == 1
        assert results[0].chunk_id == "fragment-2"  # lower distance -> higher score

    def test_different_chunk_types_of_the_same_symbol_are_kept_separate(self) -> None:
        store = _FakeVectorStore(
            [
                _match("fn", symbol_id="s1", chunk_type="function"),
                _match("ep", symbol_id="s1", chunk_type="api_endpoint"),
            ]
        )
        results = search(FakeEmbeddingProvider(), store, _settings(), _query(top_k=10))
        assert {r.chunk_id for r in results} == {"fn", "ep"}

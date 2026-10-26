"""The ChromaDB adapter: collection naming/isolation, upsert validation,
search mapping, filter allow-listing, deletion, and controlled failures.

Uses a real (embedded, local, tmp_path-backed) ChromaDB for most cases —
no network involved, so this stays fast — and mocks the underlying
client only for the "controlled failure" cases.
"""

import pytest

from app.core.config import Settings
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import CodeChunk
from app.indexing.chroma_store import ChromaVectorStore, sanitize_collection_name
from app.indexing.exceptions import (
    InvalidFilterError,
    VectorStoreConnectionError,
    VectorStoreQueryError,
)


def _settings(tmp_path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "chroma_persist_directory": str(tmp_path),
        "chroma_collection_prefix": "codegraph",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _make_chunk(
    *,
    repository_id: str = "repo-1",
    chunk_id: str = "chunk-1",
    content: str = "def f(): pass",
    chunk_type: ChunkType = ChunkType.FUNCTION,
    file_path: str = "m.py",
    symbol_id: str | None = "sym-1",
    qualified_name: str | None = "m.f",
) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        repository_id=repository_id,
        file_id="file-1",
        symbol_id=symbol_id,
        parent_symbol_id=None,
        chunk_type=chunk_type,
        language="python",
        qualified_name=qualified_name,
        display_name="f",
        file_path=file_path,
        start_line=1,
        end_line=2,
        content=content,
        content_hash="hash-1",
        parser_version="1",
        embedding_model="fake-model",
        fragment_index=0,
        fragment_count=1,
    )


class TestSanitizeCollectionName:
    def test_deterministic_for_the_same_input(self) -> None:
        name_a = sanitize_collection_name("repo-123", prefix="codegraph")
        name_b = sanitize_collection_name("repo-123", prefix="codegraph")
        assert name_a == name_b

    def test_different_repository_ids_get_different_names(self) -> None:
        name_a = sanitize_collection_name("repo-a", prefix="codegraph")
        name_b = sanitize_collection_name("repo-b", prefix="codegraph")
        assert name_a != name_b

    def test_never_equals_the_raw_repository_id(self) -> None:
        repository_id = "my-repo"
        assert sanitize_collection_name(repository_id, prefix="codegraph") != repository_id

    def test_stays_within_chroma_length_limits(self) -> None:
        name = sanitize_collection_name("x" * 200, prefix="codegraph")
        assert 3 <= len(name) <= 63

    def test_only_uses_allowed_characters(self) -> None:
        name = sanitize_collection_name("Repo With Spaces!!! And $ymbols", prefix="codegraph")
        assert all(c.isalnum() or c in "_-" for c in name)
        assert name[0].isalnum()
        assert name[-1].isalnum()

    def test_names_that_normalize_the_same_way_still_dont_collide(self) -> None:
        name_a = sanitize_collection_name("repo!!!", prefix="codegraph")
        name_b = sanitize_collection_name("repo$$$", prefix="codegraph")
        assert name_a != name_b


class TestUpsertAndSearch:
    def test_upsert_then_search_returns_the_document(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        chunk = _make_chunk()

        store.upsert("repo-1", [chunk], [[0.1, 0.2, 0.3]])
        matches = store.search("repo-1", [0.1, 0.2, 0.3], top_k=5)

        assert len(matches) == 1
        assert matches[0].chunk_id == "chunk-1"
        assert matches[0].content == "def f(): pass"
        assert matches[0].metadata["qualified_name"] == "m.f"
        assert matches[0].distance is not None

    def test_upsert_rejects_mismatched_lengths(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        chunk = _make_chunk()

        with pytest.raises(VectorStoreQueryError):
            store.upsert("repo-1", [chunk], [[0.1, 0.2], [0.3, 0.4]])

    def test_upsert_with_no_chunks_is_a_no_op(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        store.upsert("repo-1", [], [])  # must not raise
        assert store.count("repo-1") == 0

    def test_reupserting_the_same_id_does_not_duplicate(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        chunk = _make_chunk()

        store.upsert("repo-1", [chunk], [[0.1, 0.2, 0.3]])
        store.upsert("repo-1", [chunk], [[0.1, 0.2, 0.3]])

        assert store.count("repo-1") == 1


class TestRepositoryIsolation:
    def test_search_never_crosses_repositories(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        chunk_a = _make_chunk(repository_id="repo-a", chunk_id="a1", qualified_name="a.f")
        chunk_b = _make_chunk(repository_id="repo-b", chunk_id="b1", qualified_name="b.f")

        store.upsert("repo-a", [chunk_a], [[0.1, 0.2, 0.3]])
        store.upsert("repo-b", [chunk_b], [[0.1, 0.2, 0.3]])

        results_a = store.search("repo-a", [0.1, 0.2, 0.3], top_k=10)
        results_b = store.search("repo-b", [0.1, 0.2, 0.3], top_k=10)

        assert {m.chunk_id for m in results_a} == {"a1"}
        assert {m.chunk_id for m in results_b} == {"b1"}

    def test_counts_are_independent_per_repository(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        store.upsert(
            "repo-a", [_make_chunk(repository_id="repo-a", chunk_id="a1")], [[0.1, 0.2, 0.3]]
        )

        assert store.count("repo-a") == 1
        assert store.count("repo-b") == 0


class TestDeletion:
    def test_delete_specific_ids_removes_only_those(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        chunk_a = _make_chunk(chunk_id="a1")
        chunk_b = _make_chunk(chunk_id="b1")
        store.upsert("repo-1", [chunk_a, chunk_b], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

        store.delete("repo-1", ["a1"])

        assert store.count("repo-1") == 1
        remaining = store.search("repo-1", [0.4, 0.5, 0.6], top_k=10)
        assert {m.chunk_id for m in remaining} == {"b1"}

    def test_delete_with_no_ids_is_a_no_op(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        store.delete("repo-1", [])  # must not raise

    def test_delete_repository_removes_all_its_documents(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        store.upsert("repo-1", [_make_chunk()], [[0.1, 0.2, 0.3]])
        assert store.count("repo-1") == 1

        store.delete_repository("repo-1")

        assert store.count("repo-1") == 0

    def test_delete_repository_never_touches_another_repository(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        store.upsert(
            "repo-a", [_make_chunk(repository_id="repo-a", chunk_id="a1")], [[0.1, 0.2, 0.3]]
        )
        store.upsert(
            "repo-b", [_make_chunk(repository_id="repo-b", chunk_id="b1")], [[0.4, 0.5, 0.6]]
        )

        store.delete_repository("repo-a")

        assert store.count("repo-a") == 0
        assert store.count("repo-b") == 1

    def test_deleting_an_already_absent_repository_does_not_raise(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        store.delete_repository("never-existed")  # must not raise


class TestMetadataFilterAllowList:
    def test_allowed_filter_key_is_applied(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        function_chunk = _make_chunk(chunk_id="f1", chunk_type=ChunkType.FUNCTION)
        class_chunk = _make_chunk(chunk_id="c1", chunk_type=ChunkType.CLASS)
        store.upsert("repo-1", [function_chunk, class_chunk], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

        results = store.search(
            "repo-1", [0.1, 0.2, 0.3], top_k=10, where={"chunk_type": "function"}
        )

        assert {m.chunk_id for m in results} == {"f1"}

    def test_disallowed_filter_key_is_rejected(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))

        with pytest.raises(InvalidFilterError):
            store.search(
                "repo-1", [0.1, 0.2, 0.3], top_k=5, where={"__raw_cypher_or_whatever": "x"}
            )

    def test_list_valued_filter_uses_in_operator(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        function_chunk = _make_chunk(chunk_id="f1", chunk_type=ChunkType.FUNCTION)
        method_chunk = _make_chunk(chunk_id="m1", chunk_type=ChunkType.METHOD)
        class_chunk = _make_chunk(chunk_id="c1", chunk_type=ChunkType.CLASS)
        store.upsert(
            "repo-1",
            [function_chunk, method_chunk, class_chunk],
            [[0.1, 0.2, 0.3], [0.15, 0.25, 0.35], [0.9, 0.9, 0.9]],
        )

        results = store.search(
            "repo-1", [0.1, 0.2, 0.3], top_k=10, where={"chunk_type": ["function", "method"]}
        )

        assert {m.chunk_id for m in results} == {"f1", "m1"}


class TestHealthCheck:
    def test_health_check_ok_for_a_working_store(self, tmp_path) -> None:
        store = ChromaVectorStore(_settings(tmp_path))
        assert store.health_check() == "ok"


class TestControlledFailures:
    def test_client_construction_failure_raises_a_controlled_error(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: object, **kwargs: object) -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr("chromadb.PersistentClient", _raise)

        with pytest.raises(VectorStoreConnectionError):
            ChromaVectorStore(_settings(tmp_path))

    def test_health_check_reports_unavailable_without_raising(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ChromaVectorStore(_settings(tmp_path))

        def _raise() -> None:
            raise RuntimeError("down")

        monkeypatch.setattr(store._client, "heartbeat", _raise)

        assert store.health_check() == "unavailable"

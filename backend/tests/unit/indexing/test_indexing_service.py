"""Indexing orchestration: initial index, unchanged-skip, changed-reembed,
stale deletion, embedding-model-change reindex, force reindex, partial
failure, repository deletion, and statistics.

Uses a FakeVectorStore (in-memory recording, no real Chroma needed) and
the real SQLite-backed manifest (via the `isolated_database` root
fixture) so manifest persistence is exercised for real.
"""

from pathlib import Path

from app.domain.retrieval.models import CodeChunk
from app.indexing.exceptions import EmbeddingProviderError, VectorStoreQueryError
from app.indexing.indexing_service import delete_repository_index, index_repository
from app.indexing.metadata import get_manifest_for_repository
from app.parsing.python.parser import PythonParser
from tests.fakes import FakeEmbeddingProvider


class FakeVectorStore:
    def __init__(self) -> None:
        self.documents: dict[str, CodeChunk] = {}
        self.upsert_batches: list[list[str]] = []
        self.deleted_ids: list[str] = []
        self.fail_upsert_after: int | None = None
        self._upsert_calls = 0

    def upsert(
        self, repository_id: str, chunks: list[CodeChunk], embeddings: list[list[float]]
    ) -> None:
        self._upsert_calls += 1
        if self.fail_upsert_after is not None and self._upsert_calls > self.fail_upsert_after:
            raise VectorStoreQueryError("simulated upsert failure")
        self.upsert_batches.append([c.id for c in chunks])
        for chunk in chunks:
            self.documents[chunk.id] = chunk

    def delete(self, repository_id: str, chunk_ids: list[str]) -> None:
        self.deleted_ids.extend(chunk_ids)
        for chunk_id in chunk_ids:
            self.documents.pop(chunk_id, None)

    def delete_repository(self, repository_id: str) -> None:
        for chunk_id in [
            cid for cid, c in self.documents.items() if c.repository_id == repository_id
        ]:
            del self.documents[chunk_id]

    def search(self, *args: object, **kwargs: object) -> list[object]:
        raise NotImplementedError

    def count(self, repository_id: str) -> int:
        return sum(1 for c in self.documents.values() if c.repository_id == repository_id)

    def health_check(self) -> str:
        return "ok"


class _CountingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self, model_name: str = "fake-test-embedding-model") -> None:
        super().__init__(model_name=model_name)
        self.embed_call_count = 0
        self.embedded_texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_call_count += 1
        self.embedded_texts.extend(texts)
        return super().embed_documents(texts)


def _parse(source: str, file_path: str = "m.py", repository_id: str = "repo-1"):
    return PythonParser().parse(source, Path(file_path), repository_id)


def _settings_with_batch_size(size: int = 100):
    from app.core.config import Settings

    return Settings(indexing_batch_size=size)  # type: ignore[call-arg]


class TestInitialIndex:
    def test_indexes_every_chunk_and_records_the_manifest(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        parsed = _parse("def f():\n    pass\n\ndef g():\n    pass\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        stats = index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        assert stats.chunk_count == 3  # module + 2 functions
        assert stats.indexed_chunk_count == 3
        assert stats.skipped_chunk_count == 0
        assert stats.deleted_stale_chunk_count == 0
        assert stats.error_count == 0
        assert vector_store.count("repo-1") == 3
        assert len(get_manifest_for_repository(session, "repo-1")) == 3
        session.close()


class TestUnchangedReindexSkipsEmbeddings:
    def test_second_identical_run_skips_all_embedding(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        parsed = _parse("def f():\n    pass\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )
        calls_after_first_run = provider.embed_call_count

        stats = index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        assert stats.indexed_chunk_count == 0
        assert stats.skipped_chunk_count == stats.chunk_count
        assert provider.embed_call_count == calls_after_first_run  # no new embed calls
        session.close()


class TestChangedSymbolReembedsOnlyChangedChunks:
    def test_only_the_changed_function_is_reembedded(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        original = _parse("def f():\n    return 1\n\n\ndef g():\n    return 2\n")
        changed = _parse("def f():\n    return 999\n\n\ndef g():\n    return 2\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[original],
        )
        stats = index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[changed],
        )

        # only `f`'s chunk changed; `g`'s function chunk and the module
        # chunk are untouched (module chunk's import/signature listing is
        # unaffected by a body-only change).
        assert stats.indexed_chunk_count == 1
        assert stats.skipped_chunk_count == stats.chunk_count - 1
        session.close()


class TestDeletedSymbolRemovesStaleDocuments:
    def test_removing_a_function_deletes_its_stale_chunk(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        with_both = _parse("def f():\n    pass\n\n\ndef g():\n    pass\n")
        only_one = _parse("def f():\n    pass\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[with_both],
        )
        stats = index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[only_one],
        )

        # `g`'s function chunk is gone, and the module chunk's content also
        # changed (its function-signature listing shrank), so the module
        # chunk's old (content-hash-derived) id becomes stale too.
        assert stats.deleted_stale_chunk_count == 2
        assert len(vector_store.deleted_ids) == 2
        remaining_manifest = get_manifest_for_repository(session, "repo-1")
        assert len(remaining_manifest) == stats.chunk_count
        session.close()


class TestEmbeddingModelChangeTriggersReindex:
    def test_changing_the_model_reembeds_everything(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        parsed = _parse("def f():\n    pass\n\n\ndef g():\n    pass\n")
        vector_store = FakeVectorStore()

        index_repository(
            session,
            _settings_with_batch_size(),
            _CountingEmbeddingProvider("model-a"),
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )
        stats = index_repository(
            session,
            _settings_with_batch_size(),
            _CountingEmbeddingProvider("model-b"),
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        assert stats.skipped_chunk_count == 0
        assert stats.indexed_chunk_count == stats.chunk_count
        session.close()


class TestForceReindex:
    def test_force_reindex_reembeds_unchanged_chunks(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        parsed = _parse("def f():\n    pass\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )
        stats = index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
            force_reindex=True,
        )

        assert stats.skipped_chunk_count == 0
        assert stats.indexed_chunk_count == stats.chunk_count
        session.close()


class TestPartialEmbeddingFailure:
    def test_failed_batch_is_not_recorded_as_indexed(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        # two functions -> at least 2 non-module chunks; batch_size=1 makes
        # each chunk its own batch, so failing "after 1 call" only breaks
        # later batches, not the first.
        parsed = _parse("def f():\n    pass\n\n\ndef g():\n    pass\n")
        vector_store = FakeVectorStore()
        vector_store.fail_upsert_after = 1  # first upsert call succeeds, rest fail

        stats = index_repository(
            session,
            _settings_with_batch_size(size=1),
            _CountingEmbeddingProvider(),
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        assert stats.error_count > 0
        manifest_entries = get_manifest_for_repository(session, "repo-1")
        # a failed batch's chunks must never appear in the manifest as indexed
        assert len(manifest_entries) == stats.indexed_chunk_count
        session.close()

    def test_embedding_provider_failure_is_isolated_to_its_batch(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        class _FlakyProvider(_CountingEmbeddingProvider):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                self.embed_call_count += 1
                if self.embed_call_count == 1:
                    raise EmbeddingProviderError("simulated failure")
                return super(_CountingEmbeddingProvider, self).embed_documents(texts)

        session = get_session_factory()()
        parsed = _parse("def f():\n    pass\n\n\ndef g():\n    pass\n")
        vector_store = FakeVectorStore()

        stats = index_repository(
            session,
            _settings_with_batch_size(size=1),
            _FlakyProvider(),
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        assert stats.error_count >= 1
        assert stats.indexed_chunk_count < stats.chunk_count
        session.close()


class TestRepositoryDeletionCleanup:
    def test_delete_repository_index_clears_store_and_manifest(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        parsed = _parse("def f():\n    pass\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )
        assert vector_store.count("repo-1") > 0

        delete_repository_index(session, vector_store, repository_id="repo-1")

        assert vector_store.count("repo-1") == 0
        assert get_manifest_for_repository(session, "repo-1") == []
        session.close()

    def test_deleting_one_repository_does_not_affect_another(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()
        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-a",
            parsed_files=[_parse("def f():\n    pass\n", repository_id="repo-a")],
        )
        index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-b",
            parsed_files=[_parse("def g():\n    pass\n", repository_id="repo-b")],
        )

        delete_repository_index(session, vector_store, repository_id="repo-a")

        assert vector_store.count("repo-a") == 0
        assert vector_store.count("repo-b") > 0
        assert get_manifest_for_repository(session, "repo-b") != []
        session.close()


class TestStatisticsCalculation:
    def test_symbol_and_file_counts(self, isolated_database) -> None:
        from app.core.database import get_session_factory

        session = get_session_factory()()
        parsed = _parse("class C:\n    def m(self):\n        pass\n\n\ndef f():\n    pass\n")
        provider = _CountingEmbeddingProvider()
        vector_store = FakeVectorStore()

        stats = index_repository(
            session,
            _settings_with_batch_size(),
            provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        assert stats.file_count == 1
        assert stats.symbol_count == 3  # class C, method m, function f
        assert stats.embedding_model == provider.model_name
        assert stats.embedding_dimension == provider.dimension
        assert stats.duration_ms >= 0
        session.close()

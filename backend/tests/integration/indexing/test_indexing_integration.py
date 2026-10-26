"""End-to-end indexing/retrieval integration tests: real embedded
ChromaDB + real SQLite manifest + deterministic fake embeddings.

Covers the indexing task's required integration scenarios: persistent
collection creation, indexing a sample repo, repeated indexing without
duplicates, conceptual search, chunk_type/file_path filtering,
update-and-reindex, delete-and-reindex, full repository deletion, and
cross-repository isolation.
"""

from tests.integration.indexing.conftest import parse

from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import VectorSearchQuery
from app.indexing.chroma_store import ChromaVectorStore
from app.indexing.indexing_service import delete_repository_index, index_repository
from app.indexing.metadata import get_manifest_for_repository
from app.indexing.retrieval_service import search

_AUTH_SOURCE = (
    "def login(email: str) -> bool:\n"
    '    """Authenticate a user by email."""\n'
    "    return True\n"
    "\n\n"
    "def logout() -> None:\n"
    '    """End the current session."""\n'
    "    return None\n"
)
_UTILS_SOURCE = "def helper(x: int) -> int:\n    return x + 1\n"


class TestPersistentCollectionCreation:
    def test_documents_survive_a_new_store_instance_pointed_at_the_same_directory(
        self, indexing_settings, db_session, embedding_provider, python_parser
    ) -> None:
        store_a = ChromaVectorStore(indexing_settings)
        parsed = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")

        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            store_a,
            repository_id="repo-1",
            parsed_files=[parsed],
        )

        store_b = ChromaVectorStore(indexing_settings)  # simulates a fresh process
        assert store_b.count("repo-1") == store_a.count("repo-1") > 0


class TestIndexingASampleRepository:
    def test_indexing_produces_the_expected_chunk_and_document_counts(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        auth = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        utils = parse(python_parser, _UTILS_SOURCE, "app/utils.py", "repo-1")

        stats = index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth, utils],
        )

        assert stats.chunk_count == 5  # 2 modules + login + logout + helper
        assert stats.indexed_chunk_count == 5
        assert stats.error_count == 0
        assert vector_store.count("repo-1") == 5


class TestRepeatedIndexingWithoutDuplicates:
    def test_second_run_over_unchanged_files_adds_no_documents(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        auth = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")

        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth],
        )
        count_after_first_run = vector_store.count("repo-1")

        stats = index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth],
        )

        assert vector_store.count("repo-1") == count_after_first_run
        assert stats.indexed_chunk_count == 0
        assert stats.skipped_chunk_count == stats.chunk_count


class TestConceptualSearch:
    def test_searching_with_a_functions_own_content_retrieves_it_first(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        # FakeEmbeddingProvider derives vectors from exact text (SHA-256), not
        # semantics — so a genuinely conceptual query can't be made
        # deterministic here. Using the target chunk's own content as the
        # query still exercises the full embed -> search -> convert ->
        # rank pipeline end-to-end deterministically. True semantic
        # retrieval is covered by the opt-in real-model test.
        auth = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth],
        )
        login_func = auth.functions[0]
        assert login_func.name == "login"
        from app.indexing.chunker import build_chunks_for_file
        from app.indexing.models import ChunkingLimits

        limits = ChunkingLimits(max_characters=4000, max_lines=200, context_lines=3)
        chunks = build_chunks_for_file(auth, repository_id="repo-1", limits=limits)
        login_chunk = next(
            c for c in chunks if c.chunk_type is ChunkType.FUNCTION and c.display_name == "login"
        )

        results = search(
            embedding_provider,
            vector_store,
            indexing_settings,
            VectorSearchQuery(repository_id="repo-1", query=login_chunk.content, top_k=5),
        )

        assert results
        assert results[0].chunk_id == login_chunk.id
        assert results[0].file_path == "app/auth.py"
        assert results[0].qualified_name == "app.auth.login"


class TestChunkTypeFiltering:
    def test_function_filter_excludes_module_chunks(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        auth = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth],
        )

        results = search(
            embedding_provider,
            vector_store,
            indexing_settings,
            VectorSearchQuery(
                repository_id="repo-1", query="login", top_k=10, chunk_types=[ChunkType.FUNCTION]
            ),
        )

        assert results
        assert all(r.chunk_type is ChunkType.FUNCTION for r in results)


class TestFilePathFiltering:
    def test_file_path_filter_only_returns_that_files_chunks(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        auth = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        utils = parse(python_parser, _UTILS_SOURCE, "app/utils.py", "repo-1")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth, utils],
        )

        results = search(
            embedding_provider,
            vector_store,
            indexing_settings,
            VectorSearchQuery(
                repository_id="repo-1", query="helper", top_k=10, file_paths=["app/utils.py"]
            ),
        )

        assert results
        assert all(r.file_path == "app/utils.py" for r in results)


class TestUpdateOneFunctionAndReindex:
    def test_only_the_modified_function_is_reembedded_and_replaced(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        original = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[original],
        )

        modified_source = _AUTH_SOURCE.replace("return True", "return bool(email)")
        modified = parse(python_parser, modified_source, "app/auth.py", "repo-1")
        stats = index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[modified],
        )

        assert stats.indexed_chunk_count == 1
        assert stats.skipped_chunk_count == stats.chunk_count - 1

        results = search(
            embedding_provider,
            vector_store,
            indexing_settings,
            VectorSearchQuery(
                repository_id="repo-1",
                query="return bool(email)",
                top_k=5,
                chunk_types=[ChunkType.FUNCTION],
                qualified_name_prefix="app.auth.login",
            ),
        )
        assert results
        assert "return bool(email)" in results[0].content


class TestDeleteOneFunctionRemovesStaleDoc:
    def test_removed_function_no_longer_appears_in_search(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        original = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[original],
        )

        login_only_source = (
            "def login(email: str) -> bool:\n"
            '    """Authenticate a user by email."""\n'
            "    return True\n"
        )
        without_logout = parse(python_parser, login_only_source, "app/auth.py", "repo-1")
        stats = index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[without_logout],
        )

        assert stats.deleted_stale_chunk_count >= 1
        results = search(
            embedding_provider,
            vector_store,
            indexing_settings,
            VectorSearchQuery(
                repository_id="repo-1", query="logout", top_k=10, chunk_types=[ChunkType.FUNCTION]
            ),
        )
        assert all(r.qualified_name != "app.auth.logout" for r in results)


class TestFullRepositoryIndexDeletion:
    def test_deletion_clears_the_vector_store_and_manifest(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        auth = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-1")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-1",
            parsed_files=[auth],
        )
        assert vector_store.count("repo-1") > 0

        delete_repository_index(db_session, vector_store, repository_id="repo-1")

        assert vector_store.count("repo-1") == 0
        assert get_manifest_for_repository(db_session, "repo-1") == []


class TestIsolationBetweenTwoRepositories:
    def test_search_and_deletion_never_cross_repositories(
        self, indexing_settings, db_session, embedding_provider, vector_store, python_parser
    ) -> None:
        auth_a = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-a")
        auth_b = parse(python_parser, _AUTH_SOURCE, "app/auth.py", "repo-b")
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-a",
            parsed_files=[auth_a],
        )
        index_repository(
            db_session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id="repo-b",
            parsed_files=[auth_b],
        )

        results_a = search(
            embedding_provider,
            vector_store,
            indexing_settings,
            VectorSearchQuery(repository_id="repo-a", query="login", top_k=30),
        )
        assert all(r.repository_id == "repo-a" for r in results_a)
        assert len(results_a) == vector_store.count("repo-a")

        delete_repository_index(db_session, vector_store, repository_id="repo-a")

        assert vector_store.count("repo-a") == 0
        assert vector_store.count("repo-b") > 0

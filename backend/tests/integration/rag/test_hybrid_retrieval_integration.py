"""End-to-end hybrid-retrieval integration tests: real Neo4j (skips
cleanly if unreachable — see conftest.py for the exact command to run
one), real embedded ChromaDB, deterministic fake embeddings, and a real
parsed sample repository.
"""

import uuid
from pathlib import Path

from tests.integration.rag.conftest import _AUTH_SOURCE, _DB_SOURCE

from app.domain.rag.enums import (
    EvidenceType,
    GraphRetrievalOperation,
    QueryIntent,
    RetrievalMode,
    SymbolResolutionStatus,
)
from app.domain.retrieval.enums import ChunkType
from app.graph.graph_builder import (
    RepositoryMetadata,
    build_repository_graph,
    delete_repository_graph,
)
from app.indexing.chunker import build_chunks_for_file
from app.indexing.indexing_service import index_repository
from app.indexing.models import ChunkingLimits
from app.parsing.python.parser import PythonParser
from app.rag.evidence import deduplicate_evidence
from app.rag.graph_retriever import GraphRetriever
from app.rag.hybrid_retriever import retrieve
from app.rag.symbol_retriever import SymbolRetriever
from app.rag.vector_retriever import VectorRetriever


def _login_chunk(repository_id: str, indexing_settings):
    parser = PythonParser()
    auth_file = parser.parse(_AUTH_SOURCE, Path("app/auth.py"), repository_id)
    limits = ChunkingLimits(
        max_characters=indexing_settings.code_chunk_max_characters,
        max_lines=indexing_settings.code_chunk_max_lines,
        context_lines=indexing_settings.code_chunk_context_lines,
    )
    chunks = build_chunks_for_file(auth_file, repository_id=repository_id, limits=limits)
    return next(
        c for c in chunks if c.chunk_type is ChunkType.FUNCTION and c.display_name == "login"
    )


class TestAnalyzeAndIndexSampleRepository:
    def test_both_stores_are_populated(self, sample_repository, neo4j_client, vector_store) -> None:
        assert vector_store.count(sample_repository) > 0
        from app.core.config import get_settings
        from app.graph import repository_graph_service

        results = repository_graph_service.search_symbols(
            neo4j_client, get_settings(), repository_id=sample_repository, query="login"
        )
        assert any(r.name == "login" for r in results)


class TestVectorRetrieval:
    def test_exact_content_query_returns_the_matching_chunk(
        self, sample_repository, vector_store, embedding_provider, indexing_settings
    ) -> None:
        login_chunk = _login_chunk(sample_repository, indexing_settings)
        retriever = VectorRetriever(embedding_provider, vector_store, indexing_settings)

        evidence = retriever.run(
            repository_id=sample_repository, query=login_chunk.content, top_k=5
        )

        assert evidence
        assert evidence[0].qualified_name == "app.auth.login"


class TestGraphRetrieval:
    def test_callers_operation_surfaces_the_real_caller(
        self, sample_repository, neo4j_client, indexing_settings
    ) -> None:
        symbol_retriever = SymbolRetriever(neo4j_client, indexing_settings)
        resolution = symbol_retriever.resolve(
            repository_id=sample_repository, query="app.auth.login"
        )
        assert resolution.resolved_symbol is not None

        graph_retriever = GraphRetriever(neo4j_client, indexing_settings)
        evidence = graph_retriever.run(
            GraphRetrievalOperation.CALLERS,
            repository_id=sample_repository,
            symbol_id=resolution.resolved_symbol.symbol_id,
        )

        assert any(e.qualified_name == "app.auth.handle_login_request" for e in evidence)


class TestHybridRetrieval:
    async def test_runs_end_to_end_and_returns_a_structured_result(
        self, sample_repository, neo4j_client, vector_store, embedding_provider, indexing_settings
    ) -> None:
        result = await retrieve(
            repository_id=sample_repository,
            question="Which functions call login()?",
            mode=RetrievalMode.HYBRID,
            top_k=None,
            settings=indexing_settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=None,
        )
        assert result.analysis.primary_intent is QueryIntent.CALLER_LOOKUP
        assert GraphRetrievalOperation.CALLERS in result.plan.graph_operations
        assert result.diagnostics.warnings == []


class TestExactSymbolPreservation:
    def test_login_resolves_exactly(
        self, sample_repository, neo4j_client, indexing_settings
    ) -> None:
        symbol_retriever = SymbolRetriever(neo4j_client, indexing_settings)
        resolution = symbol_retriever.resolve(
            repository_id=sample_repository, query="app.auth.login"
        )
        assert resolution.status is SymbolResolutionStatus.EXACT
        assert resolution.resolved_symbol is not None
        assert resolution.resolved_symbol.qualified_name == "app.auth.login"
        assert resolution.resolved_symbol.file_path == "app/auth.py"


class TestCallerQuerySurfacesCallsEvidence:
    async def test_full_pipeline_surfaces_a_calls_relationship(
        self, sample_repository, neo4j_client, vector_store, embedding_provider, indexing_settings
    ) -> None:
        result = await retrieve(
            repository_id=sample_repository,
            question="Which functions call login()?",
            mode=RetrievalMode.HYBRID,
            top_k=None,
            settings=indexing_settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=None,
        )
        assert any(item.evidence.relationship_type == "CALLS" for item in result.evidence)
        assert any(
            item.evidence.qualified_name == "app.auth.handle_login_request"
            for item in result.evidence
        )


class TestDependencyQuerySurfacesGraphEvidence:
    async def test_full_pipeline_surfaces_graph_evidence(
        self, sample_repository, neo4j_client, vector_store, embedding_provider, indexing_settings
    ) -> None:
        result = await retrieve(
            repository_id=sample_repository,
            question="What does AdminAuthService depend on?",
            mode=RetrievalMode.HYBRID,
            top_k=None,
            settings=indexing_settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=None,
        )
        assert result.analysis.primary_intent is QueryIntent.DEPENDENCY_LOOKUP
        assert result.total_graph_candidates >= 1


class TestSemanticLocationQuerySurfacesSourceChunks:
    async def test_vector_mode_surfaces_a_code_chunk(
        self, sample_repository, neo4j_client, vector_store, embedding_provider, indexing_settings
    ) -> None:
        login_chunk = _login_chunk(sample_repository, indexing_settings)

        result = await retrieve(
            repository_id=sample_repository,
            question=login_chunk.content,
            mode=RetrievalMode.VECTOR,
            top_k=None,
            settings=indexing_settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=None,
        )
        assert result.evidence
        assert result.evidence[0].evidence.evidence_type is EvidenceType.CODE_CHUNK
        assert result.evidence[0].evidence.file_path == "app/auth.py"


class TestDuplicateVectorAndGraphSymbolsAreFused:
    def test_login_from_both_channels_merges_into_one_item(
        self, sample_repository, neo4j_client, vector_store, embedding_provider, indexing_settings
    ) -> None:
        symbol_retriever = SymbolRetriever(neo4j_client, indexing_settings)
        resolution = symbol_retriever.resolve(
            repository_id=sample_repository, query="app.auth.login"
        )
        login_symbol_id = resolution.resolved_symbol.symbol_id

        graph_retriever = GraphRetriever(neo4j_client, indexing_settings)
        graph_evidence = graph_retriever.run(
            GraphRetrievalOperation.SYMBOL_DETAILS,
            repository_id=sample_repository,
            symbol_id=login_symbol_id,
        )

        login_chunk = _login_chunk(sample_repository, indexing_settings)
        vector_retriever = VectorRetriever(embedding_provider, vector_store, indexing_settings)
        vector_evidence = vector_retriever.run(
            repository_id=sample_repository, query=login_chunk.content, top_k=5
        )

        deduped = deduplicate_evidence(graph_evidence + vector_evidence)
        matching = [d for d in deduped if d.evidence.symbol_id == login_symbol_id]

        assert len(matching) == 1
        assert len(matching[0].sources) == 2


class TestRepositoryIsolation:
    def test_two_repositories_never_cross_contaminate(
        self,
        sample_repository,
        neo4j_client,
        vector_store,
        embedding_provider,
        indexing_settings,
        isolated_database,
    ) -> None:
        from app.core.database import get_session_factory

        other_repository_id = f"itest-rag-other-{uuid.uuid4()}"
        parser = PythonParser()
        other_file = parser.parse(_DB_SOURCE, Path("app/db.py"), other_repository_id)
        build_repository_graph(
            neo4j_client,
            RepositoryMetadata(
                repository_id=other_repository_id,
                name="other-repo",
                source_type="local_path",
                source_url=None,
                default_branch=None,
                commit_hash=None,
                parser_version="1",
            ),
            [other_file],
            {"app/db.py": _DB_SOURCE.count("\n") + 1},
        )
        session = get_session_factory()()
        index_repository(
            session,
            indexing_settings,
            embedding_provider,
            vector_store,
            repository_id=other_repository_id,
            parsed_files=[other_file],
        )
        session.close()

        try:
            symbol_retriever = SymbolRetriever(neo4j_client, indexing_settings)
            other_resolution = symbol_retriever.resolve(
                repository_id=other_repository_id, query="login"
            )
            assert (
                other_resolution.resolved_symbol is None
            )  # `login` only exists in sample_repository

            sample_count = vector_store.count(sample_repository)
            other_count = vector_store.count(other_repository_id)
            assert sample_count > 0
            assert other_count > 0
            assert sample_count != 0 and other_count != 0
        finally:
            delete_repository_graph(neo4j_client, other_repository_id)
            vector_store.delete_repository(other_repository_id)

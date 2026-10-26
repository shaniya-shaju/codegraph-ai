"""End-to-end hybrid retrieval with fake graph and fake vector services —
see the hybrid-retrieval task's "Hybrid retriever" test list.

Graph access is faked by monkeypatching the functions on
``app.graph.repository_graph_service`` directly (the actual module both
``SymbolRetriever`` and ``GraphRetriever`` use as their default
dependency) — no real Neo4j. Vector access is faked by passing plain
Python objects satisfying the ``EmbeddingProvider``/``VectorStore``
protocols directly into ``retrieve()`` — no real Chroma.
"""

import pytest

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, RelationshipType, SymbolMatchType
from app.domain.graph.models import (
    GraphEdge,
    GraphNode,
    GraphStatistics,
    GraphSubgraph,
    SymbolSearchResult,
)
from app.domain.rag.enums import RetrievalMode
from app.domain.retrieval.enums import ChunkType
from app.domain.retrieval.models import VectorSearchResult
from app.graph import repository_graph_service
from app.rag.hybrid_retriever import retrieve
from tests.fakes import FakeEmbeddingProvider


class _FakeVectorStore:
    def __init__(self, matches: list[VectorSearchResult] | None = None) -> None:
        self._matches = matches or []

    def search(self, repository_id, query_embedding, *, top_k, where=None):
        from app.indexing.vector_store import VectorStoreMatch

        return [
            VectorStoreMatch(
                chunk_id=r.chunk_id,
                content=r.content,
                distance=r.distance,
                metadata={
                    "symbol_id": r.symbol_id,
                    "chunk_type": r.chunk_type.value,
                    "qualified_name": r.qualified_name,
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                },
            )
            for r in self._matches[:top_k]
        ]

    def upsert(self, *a, **k):
        raise NotImplementedError

    def delete(self, *a, **k):
        raise NotImplementedError

    def delete_repository(self, *a, **k):
        raise NotImplementedError

    def count(self, repository_id):
        raise NotImplementedError

    def health_check(self):
        return "ok"


def _vector_result(
    chunk_id="v1", qualified_name="app.auth.login", file_path="app/auth.py"
) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        repository_id="repo-1",
        symbol_id="sym-login",
        chunk_type=ChunkType.FUNCTION,
        qualified_name=qualified_name,
        file_path=file_path,
        start_line=10,
        end_line=20,
        content="def login(): ...",
        score=0.8,
        distance=0.2,
    )


def _node(
    node_id="sym-login", label=NodeLabel.FUNCTION, name="login", qualified_name="app.auth.login"
) -> GraphNode:
    return GraphNode(
        id=node_id,
        repository_id="repo-1",
        label=label,
        name=name,
        qualified_name=qualified_name,
        file_path="app/auth.py",
        start_line=10,
        end_line=20,
    )


@pytest.fixture
def graph_service_patch(monkeypatch: pytest.MonkeyPatch):
    """Patches every function hybrid_retriever's graph-side components
    call by default, with sensible empty defaults each test can override."""
    state = {
        "search_symbols": [],
        "get_symbol": None,
        "get_callers": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        ),
        "get_callees": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        ),
        "get_dependencies": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        ),
        "get_symbol_neighbors": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        ),
        "get_repository_overview": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=10
        ),
        "get_statistics": GraphStatistics(
            repository_id="repo-1",
            node_counts={},
            relationship_counts={},
            unresolved_call_count=0,
            parse_error_count=0,
        ),
        "find_path": GraphSubgraph(
            nodes=[], edges=[], truncated=False, traversal_depth=1, result_limit=1
        ),
    }

    monkeypatch.setattr(
        repository_graph_service, "search_symbols", lambda *a, **k: state["search_symbols"]
    )
    monkeypatch.setattr(repository_graph_service, "get_symbol", lambda *a, **k: state["get_symbol"])
    monkeypatch.setattr(
        repository_graph_service, "get_callers", lambda *a, **k: state["get_callers"]
    )
    monkeypatch.setattr(
        repository_graph_service, "get_callees", lambda *a, **k: state["get_callees"]
    )
    monkeypatch.setattr(
        repository_graph_service, "get_dependencies", lambda *a, **k: state["get_dependencies"]
    )
    monkeypatch.setattr(
        repository_graph_service,
        "get_symbol_neighbors",
        lambda *a, **k: state["get_symbol_neighbors"],
    )
    monkeypatch.setattr(
        repository_graph_service,
        "get_repository_overview",
        lambda *a, **k: state["get_repository_overview"],
    )
    monkeypatch.setattr(
        repository_graph_service, "get_statistics", lambda *a, **k: state["get_statistics"]
    )
    monkeypatch.setattr(repository_graph_service, "find_path", lambda *a, **k: state["find_path"])
    return state


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


async def _run(
    question: str, *, mode: RetrievalMode = RetrievalMode.HYBRID, vector_matches=None, top_k=None
):
    return await retrieve(
        repository_id="repo-1",
        question=question,
        mode=mode,
        top_k=top_k,
        settings=_settings(),
        neo4j_client=None,  # type: ignore[arg-type]
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=_FakeVectorStore(vector_matches or []),
        llm_provider=None,
    )


class TestSemanticLocationQuery:
    async def test_where_is_authentication_implemented_surfaces_source_chunks(
        self, graph_service_patch
    ) -> None:
        result = await _run(
            "Where is authentication implemented?", vector_matches=[_vector_result()]
        )

        assert result.analysis.primary_intent.value == "code_location"
        assert result.total_vector_candidates == 1
        assert any(item.evidence.source.value == "vector" for item in result.evidence)
        assert result.diagnostics.retrieval_duration_ms >= 0


class TestCallerLookup:
    async def test_which_functions_call_login_surfaces_calls_evidence(
        self, graph_service_patch
    ) -> None:
        graph_service_patch["search_symbols"] = [
            SymbolSearchResult(
                symbol_id="sym-login",
                symbol_type=NodeLabel.FUNCTION,
                name="login",
                qualified_name="app.auth.login",
                file_path="app/auth.py",
                start_line=10,
                end_line=20,
                match_type=SymbolMatchType.EXACT_NAME,
            )
        ]
        caller = _node("caller-1", name="handle_request", qualified_name="app.api.handle_request")
        graph_service_patch["get_callers"] = GraphSubgraph(
            nodes=[caller],
            edges=[
                GraphEdge(
                    id="e1",
                    repository_id="repo-1",
                    source_id="caller-1",
                    target_id="sym-login",
                    relationship_type=RelationshipType.CALLS,
                )
            ],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )

        result = await _run("Which functions call login()?")

        assert result.analysis.primary_intent.value == "caller_lookup"
        assert result.resolved_symbols[0].resolved_symbol is not None
        assert result.total_graph_candidates >= 1
        assert any(item.evidence.relationship_type == "CALLS" for item in result.evidence)


class TestDependencyLookup:
    async def test_what_depends_on_user_repository_surfaces_graph_evidence(
        self, graph_service_patch
    ) -> None:
        graph_service_patch["search_symbols"] = [
            SymbolSearchResult(
                symbol_id="sym-repo",
                symbol_type=NodeLabel.CLASS,
                name="UserRepository",
                qualified_name="app.db.UserRepository",
                file_path="app/db.py",
                start_line=1,
                end_line=30,
                match_type=SymbolMatchType.EXACT_NAME,
            )
        ]
        dep = _node(
            "dep-1", label=NodeLabel.EXTERNAL_DEPENDENCY, name="sqlalchemy", qualified_name=None
        )
        graph_service_patch["get_dependencies"] = GraphSubgraph(
            nodes=[dep],
            edges=[
                GraphEdge(
                    id="e2",
                    repository_id="repo-1",
                    source_id="sym-repo",
                    target_id="dep-1",
                    relationship_type=RelationshipType.DEPENDS_ON,
                )
            ],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )

        result = await _run("What depends on UserRepository?")

        assert result.analysis.primary_intent.value == "dependency_lookup"
        assert result.total_graph_candidates >= 1


class TestArchitectureQuery:
    async def test_how_is_this_project_structured_uses_repository_overview(
        self, graph_service_patch
    ) -> None:
        graph_service_patch["get_repository_overview"] = GraphSubgraph(
            nodes=[_node("mod-1", label=NodeLabel.MODULE, name="auth", qualified_name="app.auth")],
            edges=[],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )
        graph_service_patch["get_statistics"] = GraphStatistics(
            repository_id="repo-1",
            node_counts={"Module": 3},
            relationship_counts={},
            unresolved_call_count=0,
            parse_error_count=0,
        )

        result = await _run("How is this project structured?", vector_matches=[_vector_result()])

        assert result.analysis.primary_intent.value == "architecture"
        assert any(
            item.evidence.evidence_type.value == "graph_statistic" for item in result.evidence
        )


class TestImpactAnalysis:
    async def test_what_happens_if_login_changes_returns_structural_evidence_only(
        self, graph_service_patch
    ) -> None:
        graph_service_patch["search_symbols"] = [
            SymbolSearchResult(
                symbol_id="sym-login",
                symbol_type=NodeLabel.FUNCTION,
                name="login",
                qualified_name="app.auth.login",
                file_path="app/auth.py",
                start_line=10,
                end_line=20,
                match_type=SymbolMatchType.EXACT_NAME,
            )
        ]
        result = await _run("What happens if login changes?")
        assert result.analysis.primary_intent.value == "impact_analysis"
        assert result.plan.use_vector is False


class TestModeIndependence:
    async def test_vector_mode_never_touches_the_graph(
        self, graph_service_patch, monkeypatch
    ) -> None:
        calls: list[str] = []
        for name in ("search_symbols", "get_callers", "get_symbol_neighbors"):
            monkeypatch.setattr(
                repository_graph_service,
                name,
                lambda *a, _n=name, **k: calls.append(_n) or graph_service_patch[_n],
            )

        result = await _run(
            "Which functions call login()?",
            mode=RetrievalMode.VECTOR,
            vector_matches=[_vector_result()],
        )

        assert calls == []
        # Regression check: this question classifies as caller_lookup,
        # whose intent-derived plan defaults use_vector to False (see
        # retrieval_planner.py) — _apply_mode_override must still force
        # vector search on for an explicit VECTOR mode request, not just
        # suppress graph/symbol search. Previously this returned zero
        # evidence silently (every plan flag False), which this test
        # didn't catch because it only checked the graph side.
        assert result.total_vector_candidates >= 1
        assert any(item.evidence.source.value == "vector" for item in result.evidence)

    async def test_graph_mode_never_touches_the_vector_store(self, graph_service_patch) -> None:
        result = await _run(
            "Where is authentication implemented?",
            mode=RetrievalMode.GRAPH,
            vector_matches=[_vector_result()],
        )
        assert result.total_vector_candidates == 0


class TestRepositoryIsolationPassthrough:
    async def test_repository_id_is_carried_through_the_result(self, graph_service_patch) -> None:
        result = await _run("Where is authentication implemented?")
        assert result.repository_id == "repo-1"
        assert all(item.evidence.repository_id == "repo-1" for item in result.evidence)


class TestDeduplicationAcrossSources:
    async def test_same_symbol_from_vector_and_graph_is_fused(self, graph_service_patch) -> None:
        graph_service_patch["search_symbols"] = [
            SymbolSearchResult(
                symbol_id="sym-login",
                symbol_type=NodeLabel.FUNCTION,
                name="login",
                qualified_name="app.auth.login",
                file_path="app/auth.py",
                start_line=10,
                end_line=20,
                match_type=SymbolMatchType.EXACT_NAME,
            )
        ]
        graph_service_patch["get_symbol"] = _node("sym-login")
        graph_service_patch["get_symbol_neighbors"] = GraphSubgraph(
            nodes=[_node("sym-login")],
            edges=[],
            truncated=False,
            traversal_depth=1,
            result_limit=10,
        )

        result = await _run(
            "Explain AuthService.login", vector_matches=[_vector_result(chunk_id="v1")]
        )

        matching = [item for item in result.evidence if item.evidence.symbol_id == "sym-login"]
        assert len(matching) == 1
        assert len(matching[0].sources) >= 2

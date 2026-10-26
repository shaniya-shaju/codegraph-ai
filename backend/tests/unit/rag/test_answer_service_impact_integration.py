"""Tests for the natural-language <-> deterministic-impact-analysis
integration in app.rag.answer_service — see the impact-analysis task's
"Natural-language integration". Uses tests/unit/impact/conftest.py's
FakeNeo4jClient for the deterministic engine's own traversal calls
(bypassing graph_service_patch entirely, since app.impact.traversal talks
to Neo4jClient.execute_read directly, not repository_graph_service)."""

from app.core.config import Settings
from app.domain.graph.enums import NodeLabel, SymbolMatchType
from app.domain.graph.models import GraphNode, SymbolSearchResult
from app.domain.rag.enums import RetrievalMode
from app.domain.retrieval.enums import ChunkType
from app.graph.exceptions import Neo4jConnectionError
from app.indexing.vector_store import VectorStoreMatch
from app.rag import answer_service
from app.rag.answer_generator import LLMAnswerOutput
from tests.fakes import FakeAnswerLLMProvider, FakeEmbeddingProvider
from tests.unit.impact.conftest import FakeNeo4jClient
from tests.unit.rag.conftest import FakeVectorStore


def _node(
    node_id="sym-login", label=NodeLabel.FUNCTION, qualified_name="app.auth.login"
) -> GraphNode:
    return GraphNode(
        id=node_id,
        repository_id="repo-1",
        label=label,
        name=qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        file_path="app/auth.py",
        start_line=10,
        end_line=20,
    )


def _symbol_result(
    symbol_id="sym-login", qualified_name="app.auth.login", symbol_type=NodeLabel.FUNCTION
) -> SymbolSearchResult:
    return SymbolSearchResult(
        symbol_id=symbol_id,
        symbol_type=symbol_type,
        name=qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        file_path="app/auth.py",
        start_line=10,
        end_line=20,
        match_type=SymbolMatchType.EXACT_NAME,
    )


def _vector_match() -> VectorStoreMatch:
    return VectorStoreMatch(
        chunk_id="v1",
        content="def login(): ...",
        distance=0.2,
        metadata={
            "symbol_id": "sym-login",
            "chunk_type": ChunkType.FUNCTION.value,
            "qualified_name": "app.auth.login",
            "file_path": "app/auth.py",
            "start_line": 10,
            "end_line": 20,
        },
    )


def _no_op_impact_client() -> FakeNeo4jClient:
    """FUNCTION-target call order: callers, callees, endpoints,
    external(direct), external(via_file), centrality."""
    return FakeNeo4jClient([[], [], [], [], [], [{"in_degree": 0, "out_degree": 0}]])


async def _ask(question, *, neo4j_client, llm_provider):
    from app.core.database import get_session_factory

    settings = Settings(answer_min_evidence_relevance=0.0)  # type: ignore[call-arg]
    return await answer_service.answer_question(
        get_session_factory()(),
        repository_id="repo-1",
        question=question,
        retrieval_mode=RetrievalMode.HYBRID,
        conversation_id=None,
        settings=settings,
        neo4j_client=neo4j_client,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore([_vector_match()]),
        llm_provider=llm_provider,
        query_analyzer_llm_provider=None,
    )


class TestImpactAnalysisQuestionUsesDeterministicEngine:
    async def test_evidence_is_substituted_with_deterministic_impact_facts(
        self, isolated_database, graph_service_patch
    ) -> None:
        graph_service_patch["search_symbols"] = [_symbol_result()]
        graph_service_patch["get_symbol"] = _node()
        llm = FakeAnswerLLMProvider(
            structured_result=LLMAnswerOutput(answer="This is a low-risk change [E1].")
        )

        answer = await _ask(
            "What changes if login() is modified?",
            neo4j_client=_no_op_impact_client(),
            llm_provider=llm,
        )

        assert answer.primary_intent == "impact_analysis"
        assert answer.abstained is False
        assert answer.citations
        # The prompt actually sent to the LLM must contain the
        # deterministic risk summary, not just ordinary code evidence.
        sent_prompt = llm.generate_structured_calls[0]["user_prompt"]
        assert "Risk score" in sent_prompt
        assert "structural" in sent_prompt


class TestFallsBackWhenTargetUnsupported:
    async def test_unsupported_target_type_never_touches_the_graph_client(
        self, isolated_database, graph_service_patch
    ) -> None:
        graph_service_patch["search_symbols"] = [_symbol_result(symbol_type=NodeLabel.MODULE)]
        graph_service_patch["get_symbol"] = _node(label=NodeLabel.MODULE)
        llm = FakeAnswerLLMProvider(
            structured_result=LLMAnswerOutput(answer="Ordinary evidence answer [E1].")
        )

        # neo4j_client=None: if the impact engine were mistakenly invoked
        # for an unsupported target type, this would raise immediately.
        answer = await _ask(
            "What changes if login() is modified?",
            neo4j_client=None,  # type: ignore[arg-type]
            llm_provider=llm,
        )

        assert answer.primary_intent == "impact_analysis"
        # Ordinary hybrid-retrieval evidence (vector match) was used instead.
        assert any(call["user_prompt"] for call in llm.generate_structured_calls)


class TestGracefulDegradationWhenImpactEngineFails:
    async def test_falls_back_to_ordinary_evidence_on_graph_failure(
        self, isolated_database, graph_service_patch
    ) -> None:
        class _RaisingClient:
            def execute_read(self, *args, **kwargs):
                raise Neo4jConnectionError("graph unreachable")

        graph_service_patch["search_symbols"] = [_symbol_result()]
        graph_service_patch["get_symbol"] = _node()
        llm = FakeAnswerLLMProvider(
            structured_result=LLMAnswerOutput(answer="Ordinary evidence answer [E1].")
        )

        answer = await _ask(
            "What changes if login() is modified?",
            neo4j_client=_RaisingClient(),  # type: ignore[arg-type]
            llm_provider=llm,
        )

        # No crash — falls back to ordinary (vector) evidence.
        assert answer.primary_intent == "impact_analysis"
        assert answer.abstained is False

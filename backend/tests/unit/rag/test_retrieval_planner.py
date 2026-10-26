"""Every intent must produce the expected combination of vector/graph/
symbol-search usage — see the hybrid-retrieval task's "Retrieval
planning"."""

from app.core.config import Settings
from app.domain.rag.enums import GraphRetrievalOperation, QueryIntent
from app.domain.rag.models import QueryAnalysis
from app.rag.retrieval_planner import build_retrieval_plan


def _analysis(intent: QueryIntent, **overrides: object) -> QueryAnalysis:
    base: dict[str, object] = dict(
        raw_question="q", normalized_question="q", primary_intent=intent, secondary_intents=[]
    )
    base.update(overrides)
    return QueryAnalysis(**base)  # type: ignore[arg-type]


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


class TestPerIntentPlans:
    def test_code_location_uses_vector_graph_and_symbol_search(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.CODE_LOCATION), settings=_settings())
        assert plan.use_vector and plan.use_graph and plan.use_symbol_search
        assert GraphRetrievalOperation.NEIGHBORS in plan.graph_operations

    def test_code_explanation_uses_vector_graph_and_symbol_search(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.CODE_EXPLANATION), settings=_settings())
        assert plan.use_vector and plan.use_graph and plan.use_symbol_search
        assert GraphRetrievalOperation.SYMBOL_DETAILS in plan.graph_operations

    def test_caller_lookup_uses_graph_and_symbol_search_but_not_vector(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.CALLER_LOOKUP), settings=_settings())
        assert plan.use_graph and plan.use_symbol_search
        assert not plan.use_vector
        assert plan.graph_operations == [GraphRetrievalOperation.CALLERS]

    def test_callee_lookup_uses_graph_and_symbol_search_but_not_vector(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.CALLEE_LOOKUP), settings=_settings())
        assert plan.use_graph and plan.use_symbol_search
        assert not plan.use_vector
        assert plan.graph_operations == [GraphRetrievalOperation.CALLEES]

    def test_dependency_lookup_uses_bounded_graph_traversal(self) -> None:
        settings = _settings()
        plan = build_retrieval_plan(_analysis(QueryIntent.DEPENDENCY_LOOKUP), settings=settings)
        assert not plan.use_vector
        assert plan.use_graph and plan.use_symbol_search
        assert plan.graph_operations == [GraphRetrievalOperation.DEPENDENCIES]
        assert 1 <= plan.graph_depth <= settings.graph_max_traversal_depth

    def test_impact_analysis_returns_structural_evidence_only(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.IMPACT_ANALYSIS), settings=_settings())
        assert not plan.use_vector
        assert plan.use_graph and plan.use_symbol_search
        assert set(plan.graph_operations) == {
            GraphRetrievalOperation.CALLERS,
            GraphRetrievalOperation.DEPENDENCIES,
            GraphRetrievalOperation.NEIGHBORS,
        }

    def test_inheritance_lookup_uses_the_inheritance_operation(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.INHERITANCE_LOOKUP), settings=_settings())
        assert not plan.use_vector
        assert plan.graph_operations == [GraphRetrievalOperation.INHERITANCE]

    def test_api_lookup_uses_the_api_handler_operation(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.API_LOOKUP), settings=_settings())
        assert plan.use_vector and plan.use_graph and plan.use_symbol_search
        assert plan.graph_operations == [GraphRetrievalOperation.API_HANDLER]

    def test_architecture_uses_repository_overview_and_no_symbol_search(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.ARCHITECTURE), settings=_settings())
        assert plan.use_vector and plan.use_graph
        assert not plan.use_symbol_search
        assert plan.graph_operations == [GraphRetrievalOperation.REPOSITORY_OVERVIEW]

    def test_general_code_question_is_vector_and_symbol_only(self) -> None:
        plan = build_retrieval_plan(
            _analysis(QueryIntent.GENERAL_CODE_QUESTION), settings=_settings()
        )
        assert plan.use_vector and not plan.use_graph and plan.use_symbol_search

    def test_unknown_is_minimal(self) -> None:
        plan = build_retrieval_plan(_analysis(QueryIntent.UNKNOWN), settings=_settings())
        assert plan.use_vector and not plan.use_graph and not plan.use_symbol_search


class TestRequestedDepthIsRespectedAndClamped:
    def test_requested_depth_is_used_when_within_bounds(self) -> None:
        settings = _settings()
        plan = build_retrieval_plan(
            _analysis(QueryIntent.DEPENDENCY_LOOKUP, requested_depth=2), settings=settings
        )
        assert plan.graph_depth == 2

    def test_requested_depth_is_clamped_to_the_configured_maximum(self) -> None:
        settings = _settings()
        plan = build_retrieval_plan(
            _analysis(QueryIntent.DEPENDENCY_LOOKUP, requested_depth=999), settings=settings
        )
        assert plan.graph_depth == settings.graph_max_traversal_depth

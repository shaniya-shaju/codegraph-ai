"""Query analysis orchestration: heuristic/llm/hybrid modes, and the
mandatory fallback-to-heuristic contract on any LLM failure — see the
hybrid-retrieval task's "LLM abstraction": "An LLM outage must never
break retrieval." Uses fake LLM providers only; no external API calls.
"""

from app.core.config import Settings
from app.domain.rag.enums import QueryIntent
from app.rag.exceptions import LLMAnalysisError
from app.rag.query_analyzer import analyze_query
from app.rag.structured_output import LLMQueryClassification


class _FakeLLMProvider:
    def __init__(
        self, *, result: LLMQueryClassification | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.calls = 0

    async def generate_structured(self, *, system_prompt, user_prompt, output_schema):
        self.calls += 1
        if self._error:
            raise self._error
        assert self._result is not None
        return self._result


def _settings(**overrides: object) -> Settings:
    base = {"query_analyzer_mode": "hybrid", "query_analyzer_llm_enabled": True}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestHeuristicMode:
    async def test_never_calls_the_llm(self) -> None:
        provider = _FakeLLMProvider(
            result=LLMQueryClassification(primary_intent=QueryIntent.ARCHITECTURE)
        )
        settings = _settings(query_analyzer_mode="heuristic")

        analysis = await analyze_query(
            "Where is authentication implemented?", settings=settings, llm_provider=provider
        )

        assert provider.calls == 0
        assert analysis.analysis_strategy == "heuristic"
        assert analysis.primary_intent is QueryIntent.CODE_LOCATION

    async def test_disabled_llm_flag_skips_the_llm_even_in_hybrid_mode(self) -> None:
        provider = _FakeLLMProvider(
            result=LLMQueryClassification(primary_intent=QueryIntent.ARCHITECTURE)
        )
        settings = _settings(query_analyzer_mode="hybrid", query_analyzer_llm_enabled=False)

        analysis = await analyze_query("hello", settings=settings, llm_provider=provider)

        assert provider.calls == 0
        assert analysis.analysis_strategy == "heuristic"

    async def test_no_provider_falls_back_to_heuristic(self) -> None:
        settings = _settings(query_analyzer_mode="llm")
        analysis = await analyze_query(
            "Where is authentication implemented?", settings=settings, llm_provider=None
        )
        assert analysis.analysis_strategy == "heuristic"


class TestLlmMode:
    async def test_uses_the_llm_result_directly(self) -> None:
        provider = _FakeLLMProvider(
            result=LLMQueryClassification(primary_intent=QueryIntent.ARCHITECTURE, symbols=["Foo"])
        )
        settings = _settings(query_analyzer_mode="llm")

        analysis = await analyze_query("random question", settings=settings, llm_provider=provider)

        assert analysis.primary_intent is QueryIntent.ARCHITECTURE
        assert analysis.analysis_strategy == "llm"
        assert "Foo" in analysis.symbols

    async def test_llm_error_falls_back_to_heuristic(self) -> None:
        provider = _FakeLLMProvider(error=LLMAnalysisError("boom"))
        settings = _settings(query_analyzer_mode="llm")

        analysis = await analyze_query(
            "Where is authentication implemented?", settings=settings, llm_provider=provider
        )

        assert analysis.analysis_strategy == "llm_fallback_heuristic"
        assert analysis.primary_intent is QueryIntent.CODE_LOCATION

    async def test_malformed_structured_output_falls_back_to_heuristic(self) -> None:
        # A provider implementation is responsible for raising
        # LLMAnalysisError on malformed output (see llm_provider.py) —
        # query_analyzer.py must handle that the same as any other failure.
        provider = _FakeLLMProvider(error=LLMAnalysisError("malformed output"))
        settings = _settings(query_analyzer_mode="hybrid")

        analysis = await analyze_query(
            "Which functions call login()?", settings=settings, llm_provider=provider
        )

        assert analysis.analysis_strategy == "llm_fallback_heuristic"
        assert analysis.primary_intent is QueryIntent.CALLER_LOOKUP


class TestHybridMode:
    async def test_confident_deterministic_intent_is_not_overridden(self) -> None:
        provider = _FakeLLMProvider(
            result=LLMQueryClassification(primary_intent=QueryIntent.ARCHITECTURE)
        )
        settings = _settings(query_analyzer_mode="hybrid")

        analysis = await analyze_query(
            "Which functions call login()?", settings=settings, llm_provider=provider
        )

        assert analysis.primary_intent is QueryIntent.CALLER_LOOKUP
        assert QueryIntent.ARCHITECTURE in analysis.secondary_intents
        assert analysis.analysis_strategy == "hybrid_merged"

    async def test_low_confidence_fallback_is_replaced_by_a_specific_llm_intent(self) -> None:
        provider = _FakeLLMProvider(
            result=LLMQueryClassification(primary_intent=QueryIntent.CODE_EXPLANATION)
        )
        settings = _settings(query_analyzer_mode="hybrid")

        analysis = await analyze_query(
            "What is the weather like today?", settings=settings, llm_provider=provider
        )

        assert analysis.primary_intent is QueryIntent.CODE_EXPLANATION
        assert analysis.analysis_strategy == "hybrid_merged"

    async def test_entities_are_unioned_from_both_strategies(self) -> None:
        provider = _FakeLLMProvider(
            result=LLMQueryClassification(
                primary_intent=QueryIntent.CALLER_LOOKUP, function_names=["helper"]
            )
        )
        settings = _settings(query_analyzer_mode="hybrid")

        analysis = await analyze_query(
            "Which functions call login()?", settings=settings, llm_provider=provider
        )

        assert "login" in analysis.function_names
        assert "helper" in analysis.function_names


class TestRequiresFlags:
    async def test_caller_lookup_requires_graph_and_exact_symbol_search(self) -> None:
        # requires_vector_search on QueryAnalysis is a broad "this is a
        # code-related question" signal, distinct from the tighter,
        # intent-specific RetrievalPlan.use_vector decision (see
        # retrieval_planner.py, which does turn vector off for
        # CALLER_LOOKUP) — see test_retrieval_planner.py for that.
        settings = _settings(query_analyzer_mode="heuristic")
        analysis = await analyze_query(
            "Which functions call login()?", settings=settings, llm_provider=None
        )
        assert analysis.requires_graph_search is True
        assert analysis.requires_exact_symbol_search is True

    async def test_unknown_question_does_not_require_vector_search(self) -> None:
        settings = _settings(query_analyzer_mode="heuristic")
        analysis = await analyze_query(
            "What is the weather like today?", settings=settings, llm_provider=None
        )
        assert analysis.requires_vector_search is False

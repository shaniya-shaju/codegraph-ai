"""LangChainStructuredLLMProvider: timeout, malformed-output rejection,
and exception wrapping — the underlying ChatAnthropic class is always
mocked here (never a real API call; see the hybrid-retrieval task's "No
external API calls in normal tests.").

The fake ``langchain_anthropic`` module is injected via ``sys.modules``
rather than requiring the real package to be installed — this keeps the
test suite installable/runnable even in environments where the optional
``langchain-anthropic`` pin hasn't been resolved, and is stricter about
"no real dependency" than monkeypatching an installed package would be.
"""

import asyncio
import sys
import types

import pytest

from app.core.config import Settings
from app.rag.exceptions import LLMAnalysisError, LLMConfigurationError
from app.rag.llm_provider import (
    LangChainStructuredLLMProvider,
    get_answer_llm_provider,
    get_structured_llm_provider,
    normalize_llm_provider,
    reset_answer_llm_provider,
    reset_structured_llm_provider,
)
from app.rag.structured_output import LLMQueryClassification


@pytest.fixture(autouse=True)
def _reset_provider_cache() -> None:
    reset_structured_llm_provider()
    reset_answer_llm_provider()
    yield
    reset_structured_llm_provider()
    reset_answer_llm_provider()


class _FakeStructuredModel:
    def __init__(
        self, *, result: object = None, exc: Exception | None = None, delay: float = 0.0
    ) -> None:
        self.result = result
        self.exc = exc
        self.delay = delay
        self.received_messages: object = None

    async def ainvoke(self, messages: object) -> object:
        self.received_messages = messages
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


def _patch_chat_anthropic(
    monkeypatch: pytest.MonkeyPatch, structured_model: _FakeStructuredModel
) -> None:
    class _FakeChatAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def with_structured_output(self, schema: type) -> _FakeStructuredModel:
            return structured_model

    fake_module = types.ModuleType("langchain_anthropic")
    fake_module.ChatAnthropic = _FakeChatAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake_module)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class TestGenerateStructured:
    async def test_returns_the_structured_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = LLMQueryClassification(primary_intent="code_explanation")  # type: ignore[arg-type]
        _patch_chat_anthropic(monkeypatch, _FakeStructuredModel(result=expected))
        provider = LangChainStructuredLLMProvider(_settings())

        result = await provider.generate_structured(
            system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
        )

        assert result is expected

    async def test_underlying_exception_is_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_chat_anthropic(monkeypatch, _FakeStructuredModel(exc=RuntimeError("boom")))
        provider = LangChainStructuredLLMProvider(_settings())

        with pytest.raises(LLMAnalysisError):
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )

    async def test_timeout_raises_llm_analysis_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_chat_anthropic(monkeypatch, _FakeStructuredModel(result=None, delay=0.5))
        provider = LangChainStructuredLLMProvider(_settings(query_analyzer_timeout_seconds=0))

        with pytest.raises(LLMAnalysisError):
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )

    async def test_malformed_output_type_raises_llm_analysis_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_chat_anthropic(monkeypatch, _FakeStructuredModel(result={"not": "the right type"}))
        provider = LangChainStructuredLLMProvider(_settings())

        with pytest.raises(LLMAnalysisError):
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )


class TestGetStructuredLlmProvider:
    def test_returns_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.rag.llm_provider.get_settings", lambda: _settings(query_analyzer_llm_enabled=False)
        )
        assert get_structured_llm_provider() is None

    def test_returns_a_provider_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.rag.llm_provider.get_settings", lambda: _settings(query_analyzer_llm_enabled=True)
        )
        provider = get_structured_llm_provider()
        assert provider is not None


class _FakeStreamChunk:
    def __init__(self, content: str) -> None:
        self.content = content


def _patch_chat_anthropic_stream(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunks: list[str] | None = None,
    exc: Exception | None = None,
) -> None:
    class _FakeChatAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def astream(self, messages: object):  # noqa: ANN201
            if exc is not None:
                raise exc
            for chunk in chunks or []:
                yield _FakeStreamChunk(chunk)

    fake_module = types.ModuleType("langchain_anthropic")
    fake_module.ChatAnthropic = _FakeChatAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake_module)


class TestGenerateTextStream:
    async def test_yields_chunks_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_chat_anthropic_stream(monkeypatch, chunks=["Hello ", "world"])
        provider = LangChainStructuredLLMProvider(_settings())

        chunks = [
            c async for c in provider.generate_text_stream(system_prompt="sys", user_prompt="user")
        ]

        assert chunks == ["Hello ", "world"]

    async def test_empty_chunks_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_chat_anthropic_stream(monkeypatch, chunks=["Hello", "", "world"])
        provider = LangChainStructuredLLMProvider(_settings())

        chunks = [
            c async for c in provider.generate_text_stream(system_prompt="sys", user_prompt="user")
        ]

        assert chunks == ["Hello", "world"]

    async def test_underlying_error_is_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_chat_anthropic_stream(monkeypatch, exc=RuntimeError("stream boom"))
        provider = LangChainStructuredLLMProvider(_settings())

        with pytest.raises(LLMAnalysisError):
            async for _ in provider.generate_text_stream(system_prompt="sys", user_prompt="user"):
                pass


class TestNormalizeLlmProvider:
    @pytest.mark.parametrize("raw", ["openai_compatible", "lmstudio", "LMStudio", " LMSTUDIO "])
    def test_openai_compatible_aliases(self, raw: str) -> None:
        assert normalize_llm_provider(raw) == "openai_compatible"

    @pytest.mark.parametrize("raw", ["anthropic", "Anthropic", "something-unknown", ""])
    def test_everything_else_falls_back_to_anthropic(self, raw: str) -> None:
        assert normalize_llm_provider(raw) == "anthropic"


def _patch_chat_openai(
    monkeypatch: pytest.MonkeyPatch, structured_model: _FakeStructuredModel
) -> dict[str, object]:
    """Same fake-module-injection pattern as ``_patch_chat_anthropic``,
    but also captures the kwargs the real ``ChatOpenAI`` would have
    received, so tests can assert on `base_url`/`model` without a real
    langchain-openai install."""
    received: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

        def with_structured_output(self, schema: type) -> _FakeStructuredModel:
            return structured_model

    fake_module = types.ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _FakeChatOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    return received


class TestOpenAiCompatibleProvider:
    """LM Studio / any OpenAI-compatible server — see llm_provider.py's
    module docstring: no separate LM-Studio-specific client exists, this
    is exactly ``ChatOpenAI`` pointed at a configurable base_url."""

    async def test_uses_the_configured_base_url_and_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        expected = LLMQueryClassification(primary_intent="code_explanation")  # type: ignore[arg-type]
        received = _patch_chat_openai(monkeypatch, _FakeStructuredModel(result=expected))
        provider = LangChainStructuredLLMProvider(
            _settings(
                llm_provider="lmstudio",
                llm_base_url="http://localhost:1234/v1",
                llm_model="llama-3.1-8b-instruct",
            )
        )

        result = await provider.generate_structured(
            system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
        )

        assert result is expected
        assert received["base_url"] == "http://localhost:1234/v1"
        assert received["model"] == "llama-3.1-8b-instruct"

    async def test_openai_compatible_provider_name_behaves_identically_to_lmstudio_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received = _patch_chat_openai(monkeypatch, _FakeStructuredModel(result=None))
        provider = LangChainStructuredLLMProvider(
            _settings(
                llm_provider="openai_compatible",
                llm_base_url="http://localhost:1234/v1",
                llm_model="llama-3.1-8b-instruct",
            )
        )
        with pytest.raises(LLMAnalysisError):
            # result=None fails the isinstance(result, output_schema) check
            # further down — this call is only here to force model
            # construction so `received` gets populated.
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )
        assert received["base_url"] == "http://localhost:1234/v1"

    async def test_missing_base_url_raises_a_configuration_error(self) -> None:
        provider = LangChainStructuredLLMProvider(
            _settings(llm_provider="lmstudio", llm_base_url=None, llm_model="llama-3.1-8b")
        )
        with pytest.raises(LLMConfigurationError, match="LLM_BASE_URL"):
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )

    async def test_missing_model_raises_a_configuration_error(self) -> None:
        provider = LangChainStructuredLLMProvider(
            _settings(
                llm_provider="lmstudio", llm_base_url="http://localhost:1234/v1", llm_model=""
            )
        )
        with pytest.raises(LLMConfigurationError, match="not configured"):
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )

    async def test_configuration_error_is_a_kind_of_llm_analysis_error(self) -> None:
        # Guarantees answer_service.py's existing `except LLMAnalysisError`
        # handling (see answer_service.py) already covers this case safely
        # — a missing/invalid local-LLM configuration must degrade to a
        # clear abstained answer, never a raw traceback.
        provider = LangChainStructuredLLMProvider(
            _settings(llm_provider="lmstudio", llm_base_url=None)
        )
        with pytest.raises(LLMAnalysisError):
            await provider.generate_structured(
                system_prompt="sys", user_prompt="user", output_schema=LLMQueryClassification
            )


class TestGetAnswerLlmProvider:
    def test_always_returns_a_provider_not_gated_by_a_toggle(self) -> None:
        # Unlike get_structured_llm_provider, answer generation has no
        # on/off setting — it's this stage's core feature.
        provider = get_answer_llm_provider()
        assert provider is not None

    def test_construction_never_touches_the_network(self) -> None:
        # Merely calling the accessor must not attempt to load/contact a
        # model (see LangChainStructuredLLMProvider's lazy _ensure_model).
        provider = get_answer_llm_provider()
        assert getattr(provider, "_model", "unset") is None

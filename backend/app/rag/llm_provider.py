"""Structured-LLM abstraction for query analysis and answer generation.

Query analysis and answer generation are never tightly coupled to a
specific LLM vendor — ``StructuredLLMProvider``/``AnswerLLMProvider`` are
the only things query_analyzer.py/answer_generator.py depend on.
LangChain (``langchain_anthropic.ChatAnthropic`` or
``langchain_openai.ChatOpenAI`` + ``with_structured_output``) lives
entirely inside ``LangChainStructuredLLMProvider``, imported lazily so
importing this module never requires network access or an API key (see
AGENTS.md rule 2: "LangChain orchestrates but never parses" — and here,
never decides graph/vector facts either, only classifies the question).

The retrieval pipeline must work with this disabled entirely — see
``get_structured_llm_provider``, which returns ``None`` unless
``QUERY_ANALYZER_LLM_ENABLED=true``.

Provider selection (see Prompt 11.5 "LM Studio Integration"): a single
``LangChainStructuredLLMProvider`` backs *every* configured provider — the
only thing that varies is which LangChain chat-model class
``_build_chat_model`` constructs and with what arguments. There is
deliberately no separate "LM Studio provider" class: LM Studio (and any
other local server exposing an OpenAI-compatible API) is just
``langchain_openai.ChatOpenAI`` pointed at a configurable ``base_url`` —
see ``normalize_llm_provider``. No LM-Studio-specific behavior exists
anywhere outside this module.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Protocol, TypeVar

from pydantic import BaseModel, SecretStr

from app.core.config import Settings, get_settings
from app.rag.exceptions import LLMAnalysisError, LLMConfigurationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# "lmstudio" is a friendly, documented alias for "openai_compatible" (see
# .env.example and docs/LOCAL_LLM_SETUP.md) — LM Studio's local server is
# a normal OpenAI-compatible chat-completions endpoint, so it doesn't get
# its own code path, only its own recommended LLM_BASE_URL value.
_OPENAI_COMPATIBLE_PROVIDER_NAMES = frozenset({"openai_compatible", "lmstudio"})


def normalize_llm_provider(raw: str) -> str:
    """Returns ``"anthropic"`` or ``"openai_compatible"`` for any
    supported ``LLM_PROVIDER`` value (case-insensitive). Unrecognized
    values fall back to ``"anthropic"`` — the historical default —
    rather than raising here; ``_build_chat_model`` is where an actually
    unusable configuration produces a clear error."""
    value = raw.strip().lower()
    if value in _OPENAI_COMPATIBLE_PROVIDER_NAMES:
        return "openai_compatible"
    return "anthropic"


class StructuredLLMProvider(Protocol):
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[T],
    ) -> T: ...


class AnswerLLMProvider(Protocol):
    """What app.rag.answer_generator depends on — a superset of
    StructuredLLMProvider adding raw-text streaming for the optional SSE
    endpoint (see answer_generator.py: structured generation is used for
    the non-streaming path, ``generate_text_stream`` for the streaming
    one; citation parsing works identically on both since it always
    parses ``[E<n>]`` markers out of the resulting answer text rather
    than trusting a separately-declared id list — see citation_validator.py).
    """

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[T],
    ) -> T: ...

    def generate_text_stream(
        self, *, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]: ...


def _build_chat_model(
    settings: Settings,
    *,
    timeout: float,
    max_retries: int,
    temperature: float | None,
    max_tokens: int | None,
) -> object:
    """Constructs the LangChain chat-model instance for whichever
    provider is configured. Raises ``LLMConfigurationError`` (a subclass
    of ``LLMAnalysisError``, so every existing call site already handles
    it safely — see that exception's docstring) for a configuration that
    can never work, rather than letting a deep SDK-level error surface
    later at call time."""
    provider = normalize_llm_provider(settings.llm_provider)

    if provider == "openai_compatible":
        if not settings.llm_base_url:
            raise LLMConfigurationError(
                "LLM_PROVIDER is set to a local/OpenAI-compatible provider "
                "(openai_compatible or lmstudio), but LLM_BASE_URL is not set. "
                "Set it to your LM Studio server's OpenAI-compatible URL, e.g. "
                "http://localhost:1234/v1 (backend running on the host) or "
                "http://host.docker.internal:1234/v1 (backend running in Docker "
                "Desktop) — see docs/LOCAL_LLM_SETUP.md."
            )
        if not settings.llm_model:
            raise LLMConfigurationError(
                "Local LLM model is not configured. Set LLM_MODEL to the exact "
                "model identifier currently loaded and served by LM Studio's "
                "local server — see docs/LOCAL_LLM_SETUP.md."
            )
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - dependency is pinned in pyproject
            raise LLMAnalysisError(
                "langchain-openai is not installed; cannot run the LLM provider."
            ) from exc
        # LM Studio accepts (and typically ignores) any non-empty API key —
        # never send an empty string, which some OpenAI-compatible servers
        # reject outright even though they don't check its value.
        api_key = settings.llm_api_key or "lm-studio"
        return ChatOpenAI(
            model=settings.llm_model,
            api_key=SecretStr(api_key),
            base_url=settings.llm_base_url,
            timeout=timeout,
            max_retries=max_retries,
            # ChatOpenAI's `temperature` field has no "use the server's
            # own default" mode when omitted here (unlike ChatAnthropic) —
            # always resolve to a concrete value.
            temperature=temperature if temperature is not None else settings.llm_temperature,
            max_completion_tokens=max_tokens
            if max_tokens is not None
            else settings.llm_max_output_tokens,
            extra_body={"thinking": {"type": "disabled"}},
        )

    if not settings.llm_model:
        raise LLMConfigurationError(
            "LLM_MODEL is not configured for the anthropic provider — see .env.example."
        )
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:  # pragma: no cover - dependency is pinned in pyproject
        raise LLMAnalysisError(
            "langchain-anthropic is not installed; cannot run the LLM provider."
        ) from exc
    return ChatAnthropic(
        model_name=settings.llm_model,
        api_key=SecretStr(settings.llm_api_key),
        timeout=timeout,
        max_retries=max_retries,
        temperature=temperature,
        # No stop sequences needed — passed explicitly because this
        # class's generated constructor stub requires it even though the
        # field itself defaults to None.
        stop=None,
        # Unlike ChatOpenAI, ChatAnthropic's max_tokens is a required int
        # (no server-side default to fall back to) — always pass a
        # concrete value. Passed via its `max_tokens_to_sample` alias,
        # which is what this class's constructor actually accepts.
        max_tokens_to_sample=max_tokens
        if max_tokens is not None
        else settings.llm_max_output_tokens,
    )


class LangChainStructuredLLMProvider:
    """Wraps whichever LangChain chat-model class ``_build_chat_model``
    selects for the configured provider (``ChatAnthropic`` or
    ``ChatOpenAI`` — see module docstring).

    The chat model is constructed lazily on first use (never at import or
    construction time), matching the lazy-loading pattern already used by
    ``SentenceTransformerProvider`` for the embedding model.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """``timeout``/``max_retries``/``temperature``/``max_tokens`` are
        explicit overrides rather than read directly from ``settings``
        inside this class, because this one provider implementation backs
        two different call sites with different needs: query analysis
        (get_structured_llm_provider — fast, deterministic, no retries)
        and answer generation (get_answer_llm_provider — the configured
        LLM_* timeout/retries/temperature/max_tokens). Omitted overrides
        default to query-analysis-appropriate values for backward
        compatibility with the existing call site.
        """
        self._settings = settings
        self._timeout = timeout if timeout is not None else settings.query_analyzer_timeout_seconds
        self._max_retries = max_retries if max_retries is not None else 0
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._model: object | None = None

    def _ensure_model(self) -> object:
        if self._model is None:
            self._model = _build_chat_model(
                self._settings,
                timeout=self._timeout,
                max_retries=self._max_retries,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        return self._model

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[T],
    ) -> T:
        try:
            model = self._ensure_model()
            structured_model = model.with_structured_output(output_schema)  # type: ignore[attr-defined]
            result = await asyncio.wait_for(
                structured_model.ainvoke([("system", system_prompt), ("human", user_prompt)]),
                timeout=self._timeout,
            )
        except LLMAnalysisError:
            raise
        except TimeoutError as exc:
            raise LLMAnalysisError("LLM generation timed out.") from exc
        except Exception as exc:
            raise LLMAnalysisError(f"LLM generation failed: {exc}") from exc

        if not isinstance(result, output_schema):
            raise LLMAnalysisError("LLM structured output did not match the expected schema.")
        return result

    async def generate_text_stream(
        self, *, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]:
        try:
            model = self._ensure_model()
            async for chunk in model.astream(  # type: ignore[attr-defined]
                [("system", system_prompt), ("human", user_prompt)]
            ):
                content = getattr(chunk, "content", None)
                if content:
                    yield str(content)
        except LLMAnalysisError:
            raise
        except Exception as exc:
            raise LLMAnalysisError(f"LLM streaming generation failed: {exc}") from exc


@lru_cache
def get_structured_llm_provider() -> StructuredLLMProvider | None:
    """Cached singleton accessor. Returns ``None`` (not a stub/no-op
    provider) unless the LLM analyzer is explicitly enabled — callers
    must already treat a missing provider as "run heuristic-only"."""
    settings = get_settings()
    if not settings.query_analyzer_llm_enabled:
        return None
    return LangChainStructuredLLMProvider(settings)


def reset_structured_llm_provider() -> None:
    get_structured_llm_provider.cache_clear()


@lru_cache
def get_answer_llm_provider() -> AnswerLLMProvider:
    """Cached singleton accessor for grounded answer generation — unlike
    ``get_structured_llm_provider``, this is never disabled by a config
    toggle (answer generation is this stage's core feature), but the
    model itself is still not constructed/contacted until first use (see
    ``LangChainStructuredLLMProvider._ensure_model``'s lazy loading) —
    importing/constructing this provider never requires network access or
    a valid API key/reachable server by itself. A missing/unreachable
    provider surfaces as a graceful abstained answer, not a crash — see
    ``LLMConfigurationError``'s docstring and answer_service.py's
    ``except LLMAnalysisError`` handling."""
    settings = get_settings()
    return LangChainStructuredLLMProvider(
        settings,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )


def reset_answer_llm_provider() -> None:
    get_answer_llm_provider.cache_clear()

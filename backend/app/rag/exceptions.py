"""RAG-layer-internal exception types.

Distinct from app.core.exceptions.AppError (HTTP-facing) — mirrors the
pattern in app.graph.exceptions / app.indexing.exceptions.
app.api.routes.retrieval catches these and translates to the appropriate
AppError subclass.
"""


class RagError(Exception):
    """Base class for hybrid-retrieval-layer-internal errors."""


class QueryAnalysisError(RagError):
    """Query analysis (heuristic or LLM) could not produce a result."""


class LLMAnalysisError(QueryAnalysisError):
    """The structured-LLM analyzer failed or returned malformed output.

    Always caught inside query_analyzer.py and converted into a fallback
    to the deterministic analyzer — never allowed to escape and break
    retrieval (see "Do not allow an LLM outage to break retrieval.").

    Also the base type raised (via app.rag.llm_provider) for answer
    generation failures more generally — app.rag.answer_generator's
    ``generate_answer`` wraps *any* exception raised while constructing
    or calling the model as ``LLMAnalysisError`` before it ever reaches
    answer_service.py, which turns it into a clear abstained-answer
    message rather than a raw traceback (see Prompt 11.5 "Environment
    validation": "Do not crash with a deep LangChain/OpenAI SDK
    traceback.").
    """


class LLMConfigurationError(LLMAnalysisError):
    """The configured LLM provider is missing required configuration
    (e.g. ``LLM_BASE_URL`` for an OpenAI-compatible/LM Studio provider,
    or an empty ``LLM_MODEL``) — distinct from a *reachable but failing*
    provider, though both are handled identically by callers (see
    ``LLMAnalysisError``'s docstring): this is a subclass specifically so
    the message can be written as actionable configuration guidance
    rather than a generic "the LLM request failed"."""


class SymbolResolutionError(RagError):
    """Symbol resolution could not be completed (e.g. the graph is
    unavailable)."""


class RetrievalPlanningError(RagError):
    """A retrieval plan could not be built for the given analysis."""


class InvalidRetrievalModeError(RagError):
    """An unsupported ``mode`` string was requested — see RetrievalMode."""


class ContextBudgetError(RagError):
    """The context budget could not be applied (e.g. an invalid bound)."""


class ConversationRepositoryMismatchError(RagError):
    """A conversation_id was reused under a different repository_id than
    it was first created for (see conversation_context.py's
    ``get_conversation_repository_id``) — see "Repository context must
    never cross conversations belonging to another repository."."""

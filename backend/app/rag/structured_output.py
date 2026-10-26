"""The structured-output schema the LLM query analyzer must fill in.

A plain Pydantic model (not a domain dataclass) because this is exactly
what gets handed to ``StructuredLLMProvider.generate_structured`` /
LangChain's ``with_structured_output`` — the boundary where an external
library's conventions are allowed to leak in, per this task's "LangChain
may be used for ... structured LLM-based query analysis." query_analyzer.py
converts an instance of this into the library-independent
``app.domain.rag.models.QueryAnalysis`` immediately after receiving it.
"""

from pydantic import BaseModel, Field

from app.domain.rag.enums import QueryIntent


class LLMQueryClassification(BaseModel):
    """What the LLM analyzer is asked to produce for one question.

    Only classification and literal-string extraction — the LLM never
    receives repository source code and never asserts that an extracted
    string actually exists in the repository (see "Query analysis should
    usually require only the user's question, not the repository
    source." / "Do not claim an entity exists ... until exact symbol
    resolution is performed").
    """

    primary_intent: QueryIntent
    secondary_intents: list[QueryIntent] = Field(default_factory=list)

    symbols: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    module_names: list[str] = Field(default_factory=list)
    class_names: list[str] = Field(default_factory=list)
    function_names: list[str] = Field(default_factory=list)
    api_routes: list[str] = Field(default_factory=list)

    requested_depth: int | None = None

    # A heuristic self-reported confidence, not a probability — see the
    # domain models module's docstring.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

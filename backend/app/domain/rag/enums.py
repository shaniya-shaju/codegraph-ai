"""Enumerations for the hybrid-retrieval domain models."""

from enum import StrEnum


class QueryIntent(StrEnum):
    """See the hybrid-retrieval task's "Query intents"."""

    CODE_LOCATION = "code_location"
    CODE_EXPLANATION = "code_explanation"
    CALLER_LOOKUP = "caller_lookup"
    CALLEE_LOOKUP = "callee_lookup"
    DEPENDENCY_LOOKUP = "dependency_lookup"
    IMPACT_ANALYSIS = "impact_analysis"
    ARCHITECTURE = "architecture"
    API_LOOKUP = "api_lookup"
    INHERITANCE_LOOKUP = "inheritance_lookup"
    GENERAL_CODE_QUESTION = "general_code_question"
    UNKNOWN = "unknown"


class QueryAnalyzerMode(StrEnum):
    """How ``query_analyzer.analyze_query`` combines the deterministic and
    LLM-based strategies — see QUERY_ANALYZER_MODE."""

    HEURISTIC = "heuristic"
    LLM = "llm"
    HYBRID = "hybrid"


class SymbolResolutionStatus(StrEnum):
    """See the hybrid-retrieval task's "Symbol resolution"."""

    EXACT = "exact"
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class EvidenceSource(StrEnum):
    VECTOR = "vector"
    GRAPH = "graph"
    SYMBOL = "symbol"
    API = "api"


class EvidenceType(StrEnum):
    CODE_CHUNK = "code_chunk"
    SYMBOL = "symbol"
    CALL_RELATIONSHIP = "call_relationship"
    DEPENDENCY_RELATIONSHIP = "dependency_relationship"
    INHERITANCE_RELATIONSHIP = "inheritance_relationship"
    API_ENDPOINT = "api_endpoint"
    MODULE = "module"
    FILE = "file"
    GRAPH_STATISTIC = "graph_statistic"


class GraphRetrievalOperation(StrEnum):
    """The closed set of graph operations the hybrid retriever may invoke —
    never arbitrary Cypher (see the task's "Graph retriever adapter")."""

    SYMBOL_DETAILS = "symbol_details"
    CALLERS = "callers"
    CALLEES = "callees"
    DEPENDENCIES = "dependencies"
    NEIGHBORS = "neighbors"
    INHERITANCE = "inheritance"
    PATHS = "paths"
    API_HANDLER = "api_handler"
    REPOSITORY_OVERVIEW = "repository_overview"


class RetrievalMode(StrEnum):
    """The retrieval-API's ``mode`` — lets vector-only/graph-only be
    evaluated independently of hybrid (see the task's "Evaluation
    readiness")."""

    VECTOR = "vector"
    GRAPH = "graph"
    HYBRID = "hybrid"

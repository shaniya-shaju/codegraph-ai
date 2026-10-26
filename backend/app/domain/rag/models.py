"""Typed hybrid-retrieval domain models — see this package's ``__init__``
docstring.

Confidence/score fields throughout this module are heuristic ranking
signals, never a mathematical probability (see the hybrid-retrieval
task's repeated "Do not treat confidence as mathematical probability" /
"These are heuristic retrieval scores, not probabilities").
"""

from dataclasses import dataclass, field
from typing import Any

from app.domain.graph.enums import NodeLabel, SymbolMatchType
from app.domain.rag.enums import (
    EvidenceSource,
    EvidenceType,
    GraphRetrievalOperation,
    QueryIntent,
    SymbolResolutionStatus,
)


@dataclass(frozen=True)
class QueryAnalysis:
    """Structured result of analyzing one natural-language question — see
    "Query analysis models"."""

    raw_question: str
    normalized_question: str
    primary_intent: QueryIntent
    secondary_intents: list[QueryIntent] = field(default_factory=list)

    symbols: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    module_names: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    function_names: list[str] = field(default_factory=list)
    api_routes: list[str] = field(default_factory=list)

    requested_depth: int | None = None
    requires_vector_search: bool = True
    requires_graph_search: bool = False
    requires_exact_symbol_search: bool = False

    confidence: float | None = None
    # e.g. "heuristic", "llm", "hybrid_merged", "llm_fallback_heuristic" —
    # see query_analyzer.py; used to populate RetrievalDiagnostics.fallbacks_used.
    analysis_strategy: str = "heuristic"


@dataclass(frozen=True)
class ResolvedSymbol:
    """A repository symbol actually confirmed to exist via exact graph
    lookup — never claimed from an entity string alone (see "Distinguish:
    mentioned entity / resolved repository symbol")."""

    symbol_id: str
    symbol_type: NodeLabel
    name: str
    qualified_name: str | None
    file_path: str | None
    start_line: int | None
    end_line: int | None
    match_type: SymbolMatchType
    confidence: float


@dataclass(frozen=True)
class SymbolResolution:
    query: str
    resolved_symbol: ResolvedSymbol | None
    candidates: list[ResolvedSymbol] = field(default_factory=list)
    status: SymbolResolutionStatus = SymbolResolutionStatus.NOT_FOUND


@dataclass(frozen=True)
class RetrievalPlan:
    """A deterministic plan for which retrieval components to run — see
    "Retrieval planning"."""

    use_vector: bool
    use_graph: bool
    use_symbol_search: bool

    vector_top_k: int
    graph_depth: int
    symbol_limit: int

    graph_operations: list[GraphRetrievalOperation] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalEvidence:
    """One normalized piece of evidence, from vector, graph, or symbol
    retrieval — see "Unified evidence model"."""

    id: str
    repository_id: str

    evidence_type: EvidenceType

    symbol_id: str | None
    qualified_name: str | None

    file_path: str | None
    start_line: int | None
    end_line: int | None

    content: str

    source: EvidenceSource

    vector_score: float | None = None
    graph_distance: int | None = None
    exact_match_score: float | None = None

    relationship_type: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreComponents:
    """See "Context-fusion ranking" — returned for debugging, never
    presented as a probability."""

    vector: float
    exact: float
    graph: float
    intent: float


@dataclass(frozen=True)
class RankedEvidence:
    """One deduplicated evidence item plus its transparent hybrid score —
    see "Evidence deduplication" / "Context-fusion ranking"."""

    evidence: RetrievalEvidence
    hybrid_score: float
    score_components: ScoreComponents
    sources: list[EvidenceSource] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalDiagnostics:
    retrieval_duration_ms: int
    vector_duration_ms: int
    graph_duration_ms: int
    analysis_duration_ms: int
    fallbacks_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HybridRetrievalResult:
    """The final, structured retrieval result for one question — see
    "Hybrid retrieval result". Deliberately carries no generated
    natural-language answer (that is a later stage)."""

    repository_id: str
    question: str

    analysis: QueryAnalysis
    plan: RetrievalPlan

    resolved_symbols: list[SymbolResolution]

    evidence: list[RankedEvidence]

    total_vector_candidates: int
    total_graph_candidates: int
    total_symbol_candidates: int

    deduplicated_count: int
    returned_count: int

    truncated: bool

    diagnostics: RetrievalDiagnostics

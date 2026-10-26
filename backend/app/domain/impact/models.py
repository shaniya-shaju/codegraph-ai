"""API-independent change-impact-analysis domain models.

These are what ``app.impact`` builds and ``app.api.routes.impact``
serializes — never a raw Neo4j driver object (mirrors app.domain.graph's
own rule 10). Every score/contribution here is a heuristic structural
signal, never a mathematical probability (see the impact-analysis task's
repeated "This is NOT a probability of failure").
"""

from dataclasses import dataclass, field

from app.domain.impact.enums import (
    ImpactSignalType,
    ImpactTargetType,
    ImpactType,
    RiskLevel,
    TestRelationshipStatus,
)


@dataclass(frozen=True)
class ImpactTarget:
    """The validated symbol change-impact analysis was run against."""

    symbol_id: str
    qualified_name: str | None
    name: str
    target_type: ImpactTargetType
    file_path: str | None
    start_line: int | None
    end_line: int | None


@dataclass(frozen=True)
class ImpactedSymbol:
    """One symbol found to be structurally related to the target, with an
    explainable path back to it — see "Every impacted symbol must explain
    WHY it is included."."""

    symbol_id: str
    qualified_name: str | None
    symbol_type: str

    file_path: str | None
    start_line: int | None
    end_line: int | None

    impact_type: ImpactType

    distance: int

    reason: str

    path: list[str] = field(default_factory=list)
    relationship_path: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImpactedEndpoint:
    """See "API endpoint impact" — HTTP metadata here is always exactly
    what the parser deterministically extracted, never invented."""

    endpoint_id: str
    http_method: str
    route_path: str
    handler_symbol_id: str
    handler_qualified_name: str | None
    distance_from_target: int
    impact_reason: str


@dataclass(frozen=True)
class ImpactedFile:
    """See "File impact" — one row per distinct file, never duplicated."""

    file_path: str
    affected_symbol_count: int
    minimum_distance: int
    impact_types: list[ImpactType] = field(default_factory=list)
    impacted_symbol_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImpactedModule:
    """See "Module impact" — module name is derived deterministically from
    qualified names already present in the graph, not guessed."""

    module_name: str
    affected_symbol_count: int
    minimum_distance: int
    impacted_symbol_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImpactSignal:
    """One inspectable contribution to the risk score — see "Risk
    explanation": "Every contribution must be inspectable."."""

    signal_type: ImpactSignalType
    raw_value: float
    normalized_value: float
    contribution: float
    explanation: str


@dataclass(frozen=True)
class ImpactDiagnostics:
    analysis_duration_ms: int
    nodes_visited: int
    edges_traversed: int
    paths_examined: int
    cycles_detected: int
    truncated_reason: str | None = None


@dataclass(frozen=True)
class ImpactAnalysisResult:
    """The deterministic change-impact-analysis result for one target —
    exists independently of any LLM (see the task's high-level
    architecture: "The deterministic ImpactAnalysisResult must exist
    independently of any LLM.")."""

    repository_id: str

    target: ImpactTarget

    risk_score: float
    risk_level: RiskLevel
    risk_signals: list[ImpactSignal]

    direct_callers: list[ImpactedSymbol]
    transitive_dependents: list[ImpactedSymbol]

    downstream_dependencies: list[ImpactedSymbol]

    affected_endpoints: list[ImpactedEndpoint]
    affected_files: list[ImpactedFile]
    affected_modules: list[ImpactedModule]

    # Combined convenience list (inheriting_classes ++ base_classes) —
    # kept alongside the two separated lists below because section 14 of
    # the task ("Represent: inheriting_classes / base_classes separately")
    # and section 21's literal model shape (one `inheritance_impacts`
    # field) both apply; see the impact-analysis task's final report for
    # this deliberate reconciliation.
    inheritance_impacts: list[ImpactedSymbol]
    inheriting_classes: list[ImpactedSymbol]
    base_classes: list[ImpactedSymbol]

    related_tests: list[ImpactedSymbol]
    test_relationship_status: TestRelationshipStatus

    traversal_depth: int

    total_impacted_symbols: int

    truncated: bool

    limitations: list[str]

    diagnostics: ImpactDiagnostics

"""Enumerations for the change-impact-analysis domain models."""

from enum import StrEnum


class ImpactTargetType(StrEnum):
    """The symbol types change-impact analysis initially supports — see
    the impact-analysis task's "Supported target symbols".

    Other graph node types (Module, File, Parameter, ExternalDependency,
    Directory, Repository) do not have equivalent change-impact semantics
    and are rejected with an ``UnsupportedTargetTypeError`` rather than
    silently analyzed as if they did.
    """

    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    CLASS = "CLASS"
    API_ENDPOINT = "API_ENDPOINT"


class ImpactType(StrEnum):
    """How one ``ImpactedSymbol`` relates to the analysis target — see
    "Support traversal concepts"."""

    DIRECT_CALLER = "DIRECT_CALLER"
    TRANSITIVE_CALLER = "TRANSITIVE_CALLER"
    CALLEE = "CALLEE"
    DEPENDENCY = "DEPENDENCY"
    INHERITING_CLASS = "INHERITING_CLASS"
    BASE_CLASS = "BASE_CLASS"
    API_ENDPOINT = "API_ENDPOINT"
    FILE = "FILE"
    MODULE = "MODULE"
    TEST_REFERENCE = "TEST_REFERENCE"


class RiskLevel(StrEnum):
    """A structural change-impact-risk heuristic bucket — NEVER a
    probability of failure (see "Risk scoring")."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ImpactSignalType(StrEnum):
    """See "Deterministic impact signals"."""

    DIRECT_CALLER_COUNT = "DIRECT_CALLER_COUNT"
    TRANSITIVE_DEPENDENT_COUNT = "TRANSITIVE_DEPENDENT_COUNT"
    AFFECTED_FILE_COUNT = "AFFECTED_FILE_COUNT"
    AFFECTED_MODULE_COUNT = "AFFECTED_MODULE_COUNT"
    PUBLIC_API_EXPOSURE = "PUBLIC_API_EXPOSURE"
    CROSS_MODULE_DEPENDENCY = "CROSS_MODULE_DEPENDENCY"
    EXTERNAL_DEPENDENCY_INTERACTION = "EXTERNAL_DEPENDENCY_INTERACTION"
    INHERITANCE_IMPACT = "INHERITANCE_IMPACT"
    GRAPH_CENTRALITY = "GRAPH_CENTRALITY"
    RELATED_TEST_SIGNAL = "RELATED_TEST_SIGNAL"


class TestRelationshipStatus(StrEnum):
    """See "Test-reference hints" — ``NO_KNOWN_TEST_REFERENCES`` must
    never be presented as "there are no tests", only as "the graph has no
    known relationship to a test symbol"."""

    __test__ = False  # not a pytest test class — name just matches domain vocabulary

    KNOWN_RELATED_TESTS = "KNOWN_RELATED_TESTS"
    NO_KNOWN_TEST_REFERENCES = "NO_KNOWN_TEST_REFERENCES"
    UNKNOWN = "UNKNOWN"

"""Enumerations for the graph domain models.

``NodeLabel`` and ``RelationshipType`` double as the allow-lists used to
validate anything that ultimately reaches Cypher (see SECURITY.md: "Do not
accept user-provided relationship names without allow-list validation").
"""

from enum import StrEnum


class NodeLabel(StrEnum):
    """See DATA_MODEL.md "Neo4j: knowledge graph schema" node types."""

    REPOSITORY = "Repository"
    DIRECTORY = "Directory"
    FILE = "File"
    MODULE = "Module"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"
    PARAMETER = "Parameter"
    EXTERNAL_DEPENDENCY = "ExternalDependency"
    API_ENDPOINT = "APIEndpoint"


class RelationshipType(StrEnum):
    """See DATA_MODEL.md "Neo4j: knowledge graph schema" relationship types."""

    CONTAINS = "CONTAINS"
    DEFINES = "DEFINES"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    HAS_PARAMETER = "HAS_PARAMETER"
    EXTENDS = "EXTENDS"
    REFERENCES = "REFERENCES"
    HANDLED_BY = "HANDLED_BY"
    DEPENDS_ON = "DEPENDS_ON"


class CallResolutionConfidence(StrEnum):
    """How confidently a CALLS edge's target was resolved.

    Only EXACT and documented PROBABLE cases create an internal CALLS
    edge — see relationship_resolver.py and the parsing task's reminder
    that call extraction never claims full resolution.
    """

    EXACT = "exact"
    PROBABLE = "probable"
    UNRESOLVED = "unresolved"


class CallResolutionStrategy(StrEnum):
    """Which resolution rule produced a CALLS edge (or failed to)."""

    QUALIFIED_NAME_EXACT = "qualified_name_exact"
    SAME_MODULE = "same_module"
    IMPORTED_SYMBOL = "imported_symbol"
    SELF_METHOD = "self_method"
    CLS_METHOD = "cls_method"
    UNIQUE_REPOSITORY_SYMBOL = "unique_repository_symbol"
    UNRESOLVED = "unresolved"


class SymbolMatchType(StrEnum):
    """How a symbol-search result matched the query string."""

    EXACT_NAME = "exact_name"
    EXACT_QUALIFIED_NAME = "exact_qualified_name"
    PREFIX = "prefix"
    CONTAINS = "contains"

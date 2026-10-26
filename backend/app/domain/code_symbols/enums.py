"""Enumerations used by the parsed-symbol domain models."""

from enum import StrEnum


class ParameterKind(StrEnum):
    """Python parameter binding kind (mirrors PEP 570 / PEP 3102 categories)."""

    POSITIONAL_ONLY = "positional_only"
    POSITIONAL = "positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_POSITIONAL = "var_positional"
    VAR_KEYWORD = "var_keyword"


class CallType(StrEnum):
    """Best-effort, syntax-only classification of a call expression.

    None of these claim the call has been resolved to a concrete symbol —
    see ARCHITECTURE.md "Change-impact-analysis design" and the parsing
    task's non-goals: cross-file call resolution happens in a later stage,
    if at all.
    """

    DIRECT = "direct"
    ATTRIBUTE = "attribute"
    CONSTRUCTOR_CANDIDATE = "constructor_candidate"
    DYNAMIC_OR_UNKNOWN = "dynamic_or_unknown"


class SymbolType(StrEnum):
    """Disambiguates the hash input used for stable symbol IDs."""

    MODULE = "module"
    FUNCTION = "function"
    CLASS = "class"
    PARAMETER = "parameter"
    IMPORT = "import"
    CALL = "call"
    ASSIGNMENT = "assignment"


class ParseErrorType(StrEnum):
    SYNTAX_ERROR = "syntax_error"
    ENCODING_ERROR = "encoding_error"
    INTERNAL_ERROR = "internal_error"

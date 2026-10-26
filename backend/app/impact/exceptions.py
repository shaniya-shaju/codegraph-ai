"""Impact-layer-internal exception types.

Distinct from app.core.exceptions.AppError (HTTP-facing) — mirrors the
pattern in app.graph.exceptions / app.rag.exceptions.
app.api.routes.impact catches these and translates to the appropriate
AppError subclass.
"""


class ImpactError(Exception):
    """Base class for change-impact-analysis-layer-internal errors."""


class UnsupportedTargetTypeError(ImpactError):
    """The resolved symbol's type has no defined change-impact semantics
    yet (see ImpactTargetType — only FUNCTION/METHOD/CLASS/API_ENDPOINT
    are supported)."""


class TargetSymbolNotFoundError(ImpactError):
    """No symbol with the given symbol_id exists in this repository's graph."""


class AmbiguousTargetError(ImpactError):
    """A qualified_name target resolved to more than one equally-ranked
    candidate — impact analysis never guesses between them."""

    def __init__(self, message: str, *, candidates: list[str]) -> None:
        super().__init__(message)
        self.candidates = candidates


class InvalidImpactParameterError(ImpactError):
    """A depth/max_nodes parameter is missing or out of the configured bounds."""

"""Graph-layer-internal exception types.

Distinct from app.core.exceptions.AppError (HTTP-facing) — mirrors the
pattern in app.parsing.exceptions. app.api.routes.graph and
app.api.routes.repositories catch these and translate to the appropriate
AppError subclass.
"""


class GraphError(Exception):
    """Base class for graph-layer-internal errors."""


class Neo4jConnectionError(GraphError):
    """Neo4j could not be reached or authenticated against."""


class Neo4jQueryError(GraphError):
    """A Cypher query failed for a reason other than connectivity."""


class TraversalLimitExceededError(GraphError):
    """A requested depth/node/edge count exceeds the configured bound."""


class InvalidRelationshipTypeError(GraphError):
    """A relationship type outside the RelationshipType allow-list was requested."""


class SymbolNotFoundError(GraphError):
    """No node with the given symbol_id exists in this repository's graph."""

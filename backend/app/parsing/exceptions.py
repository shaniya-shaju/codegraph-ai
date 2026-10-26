"""Parser-internal exception types.

Distinct from app.core.exceptions.AppError (HTTP-facing): the parsing
layer must stay independent of the API/graph/DB layers (AGENTS.md rule 9),
so it defines and raises its own exceptions rather than importing the
HTTP error contract.
"""


class ParserError(Exception):
    """Base class for parser-internal errors."""


class UnsupportedFileError(ParserError):
    """No registered parser supports this file."""


class SourceDecodingError(ParserError):
    """Source bytes could not be decoded as valid UTF-8 text."""


class DuplicateParserRegistrationError(ParserError):
    """A parser for this language is already registered."""

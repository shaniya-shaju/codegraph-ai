"""Parser registry: register language parsers, resolve one by file.

Deliberately tiny (see AGENTS.md rule 9) — no plugin discovery, no config
files. Adding a language later is "construct it and call .register()",
not a change to this module or to any caller of ParserRegistry.
"""

from pathlib import Path, PurePosixPath

from app.domain.code_symbols.enums import ParseErrorType, SymbolType
from app.domain.code_symbols.models import ParsedFile, ParseError
from app.parsing.base import LanguageParser
from app.parsing.exceptions import DuplicateParserRegistrationError, SourceDecodingError
from app.parsing.source_utils import (
    compute_content_hash,
    decode_source,
    derive_module_name,
    generate_symbol_id,
)


class ParserRegistry:
    """Holds zero or more LanguageParser implementations, one per language."""

    def __init__(self) -> None:
        self._parsers_by_language: dict[str, LanguageParser] = {}
        self._registration_order: list[str] = []

    def register(self, parser: LanguageParser) -> None:
        if parser.language in self._parsers_by_language:
            raise DuplicateParserRegistrationError(
                f"A parser for language {parser.language!r} is already registered."
            )
        self._parsers_by_language[parser.language] = parser
        self._registration_order.append(parser.language)

    def get_parser_for_file(self, file_path: Path) -> LanguageParser | None:
        """Return the first registered parser that supports `file_path`,
        or None if no registered parser handles it."""
        for language in self._registration_order:
            parser = self._parsers_by_language[language]
            if parser.supports(file_path):
                return parser
        return None

    def get_parser_by_language(self, language: str) -> LanguageParser | None:
        return self._parsers_by_language.get(language)

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self._registration_order)


def build_default_registry() -> ParserRegistry:
    """Registry pre-populated with the parsers this codebase currently ships."""
    from app.parsing.python.parser import PythonParser

    registry = ParserRegistry()
    registry.register(PythonParser())
    return registry


def parse_source_bytes(
    registry: ParserRegistry,
    raw_bytes: bytes,
    file_path: Path,
    repository_id: str,
) -> ParsedFile | None:
    """Decode + dispatch to the right parser for `file_path`.

    Returns None if no registered parser supports `file_path` — callers
    (e.g. a repository scan) decide what to do with unsupported files,
    typically just skipping them. An unsupported *encoding* is different:
    the file *is* a type this registry knows how to parse, but its bytes
    aren't valid UTF-8 — that becomes a ParsedFile carrying a single
    recorded ParseError (see the parsing task: "Unsupported file encoding
    should produce a controlled error"), not a raised exception and not a
    silently-skipped file.
    """
    parser = registry.get_parser_for_file(file_path)
    if parser is None:
        return None

    try:
        source = decode_source(raw_bytes)
    except SourceDecodingError as exc:
        posix_path = PurePosixPath(file_path.as_posix())
        module_name = derive_module_name(posix_path)
        file_id = generate_symbol_id(
            repository_id=repository_id,
            file_path=str(posix_path),
            symbol_type=SymbolType.MODULE.value,
            qualified_name=module_name,
            start_line=1,
        )
        return ParsedFile(
            id=file_id,
            repository_id=repository_id,
            file_path=str(posix_path),
            module_name=module_name,
            language=parser.language,
            content_hash=compute_content_hash(raw_bytes),
            parse_errors=[
                ParseError(
                    error_type=ParseErrorType.ENCODING_ERROR,
                    message=str(exc),
                    file_path=str(posix_path),
                    location=None,
                    recoverable=False,
                )
            ],
            parser_version="0",
        )

    return parser.parse(source, file_path, repository_id)

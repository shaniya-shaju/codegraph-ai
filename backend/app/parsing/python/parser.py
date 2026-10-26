"""The Python LanguageParser implementation.

Orchestrates decode-already-done -> Tree-sitter parse -> symbol_builder,
and turns any unexpected failure into a recorded, non-crashing ParseError
instead of propagating — see the parsing task's "Parsing failures in one
file must not crash analysis of an entire repository."
"""

from pathlib import Path, PurePosixPath

import tree_sitter_python as tspython
from tree_sitter import Language
from tree_sitter import Parser as TreeSitterParser

from app.domain.code_symbols.enums import ParseErrorType, SymbolType
from app.domain.code_symbols.models import ParsedFile, ParseError
from app.parsing.models import ParseContext
from app.parsing.python.symbol_builder import build_parsed_file
from app.parsing.source_utils import compute_content_hash, derive_module_name, generate_symbol_id

PARSER_VERSION = "1"

_PY_LANGUAGE = Language(tspython.language())


class PythonParser:
    """Deterministic, non-executing Python source parser (see SECURITY.md)."""

    language = "python"

    def __init__(self) -> None:
        self._parser = TreeSitterParser(_PY_LANGUAGE)

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix == ".py"

    def parse(self, source: str, file_path: Path, repository_id: str) -> ParsedFile:
        posix_path = PurePosixPath(file_path.as_posix())
        module_name = derive_module_name(posix_path)
        source_bytes = source.encode("utf-8")

        try:
            tree = self._parser.parse(source_bytes)
            ctx = ParseContext(
                source_bytes=source_bytes,
                tree=tree,
                file_path=str(posix_path),
                module_name=module_name,
                repository_id=repository_id,
                parser_version=PARSER_VERSION,
            )
            return build_parsed_file(ctx, tree.root_node)
        except Exception as exc:  # noqa: BLE001 - one file must never abort a repository scan
            return _build_error_parsed_file(
                repository_id=repository_id,
                file_path=str(posix_path),
                module_name=module_name,
                source_bytes=source_bytes,
                message=f"Internal parser failure: {exc}",
            )


def _build_error_parsed_file(
    *,
    repository_id: str,
    file_path: str,
    module_name: str,
    source_bytes: bytes,
    message: str,
) -> ParsedFile:
    file_id = generate_symbol_id(
        repository_id=repository_id,
        file_path=file_path,
        symbol_type=SymbolType.MODULE.value,
        qualified_name=module_name,
        start_line=1,
    )
    return ParsedFile(
        id=file_id,
        repository_id=repository_id,
        file_path=file_path,
        module_name=module_name,
        language="python",
        content_hash=compute_content_hash(source_bytes),
        parse_errors=[
            ParseError(
                error_type=ParseErrorType.INTERNAL_ERROR,
                message=message,
                file_path=file_path,
                location=None,
                recoverable=False,
            )
        ],
        parser_version=PARSER_VERSION,
    )

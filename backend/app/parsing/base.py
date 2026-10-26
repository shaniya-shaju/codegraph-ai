"""Language-agnostic parser interface.

Any future language parser (JavaScript, Java, ...) implements this same
protocol so the registry and its callers never need to change — see
AGENTS.md rule 10 and the parsing task's "Support future JavaScript or
Java parsers without modifying calling code."
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.code_symbols.models import ParsedFile


@runtime_checkable
class LanguageParser(Protocol):
    """A deterministic, non-executing source-to-domain-model parser."""

    language: str

    def supports(self, file_path: Path) -> bool:
        """Whether this parser should handle `file_path` (by extension)."""
        ...

    def parse(
        self,
        source: str,
        file_path: Path,
        repository_id: str,
    ) -> ParsedFile:
        """Parse `source` (already-decoded text) into a ParsedFile.

        `file_path` must be repository-relative — it is preserved verbatim
        into every SourceLocation and used to derive the module name.
        Must never execute, import, or otherwise run `source`.
        """
        ...

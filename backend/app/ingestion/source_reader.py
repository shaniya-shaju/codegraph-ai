"""Safe, read-only repository source-file access — see the frontend-
integration task's "Source Code Viewer": "add the smallest possible
read-only endpoint... with validated repository-relative path and
optional line range." Only ever reads bytes already on disk in a
repository's own workspace (see app.ingestion.workspace) — never
executes, imports, or evaluates anything (same rule as the rest of
app.ingestion; see SECURITY.md "Parsing safety").
"""

from dataclasses import dataclass
from pathlib import Path

from app.ingestion.analysis import repository_workspace

# A little padding around a requested (citation) line range, so the
# viewer shows some surrounding context — same spirit as the source-
# viewer mockup in the frontend-integration task ("20 | ...", "21 | ...").
_CONTEXT_LINES = 5
# Bounded response size when no line range is given at all (avoid ever
# serving an unbounded file into the browser).
_MAX_LINES_WITHOUT_RANGE = 400
_MAX_FILE_BYTES = 2_000_000


class SourceFileError(Exception):
    """Base class for source-reading errors."""


class SourceFileNotFoundError(SourceFileError):
    """No such file (or no such repository workspace) exists on disk."""


class UnsafePathError(SourceFileError):
    """The requested path is absolute, empty, or escapes the repository
    workspace — see SECURITY.md "Repository acquisition safety"."""


class SourceFileTooLargeError(SourceFileError):
    """The file exceeds the preview size cap."""


@dataclass(frozen=True)
class SourceSnippet:
    file_path: str
    start_line: int
    end_line: int
    total_lines: int
    content: str
    truncated: bool


def _resolve_safe_path(workspace: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise UnsafePathError("path must be a non-empty repository-relative path.")

    workspace_resolved = workspace.resolve()
    candidate = (workspace_resolved / relative_path).resolve()
    try:
        candidate.relative_to(workspace_resolved)
    except ValueError as exc:
        raise UnsafePathError("path escapes the repository workspace.") from exc

    if not candidate.is_file():
        raise SourceFileNotFoundError(f"No file at {relative_path!r}.")
    return candidate


def read_source_snippet(
    repository_id: str,
    *,
    relative_path: str,
    start_line: int | None,
    end_line: int | None,
) -> SourceSnippet:
    """Reads a bounded, line-numbered snippet of one file from a
    repository's on-disk workspace.

    With a line range: returns that range plus a small context margin.
    Without one: returns the file's first ``_MAX_LINES_WITHOUT_RANGE``
    lines — never the whole file unconditionally.
    """
    workspace = repository_workspace(repository_id)
    if not workspace.exists():
        raise SourceFileNotFoundError(
            "This repository's workspace is no longer available on disk — reimport it "
            "(upload or clone) to view source."
        )

    resolved = _resolve_safe_path(workspace, relative_path)

    raw = resolved.read_bytes()
    if len(raw) > _MAX_FILE_BYTES:
        raise SourceFileTooLargeError("This file is too large to preview.")

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    if start_line is not None:
        lo = max(1, start_line - _CONTEXT_LINES)
        hi = min(total_lines, (end_line or start_line) + _CONTEXT_LINES)
    else:
        lo = 1
        hi = min(total_lines, _MAX_LINES_WITHOUT_RANGE)
    hi = max(hi, lo)

    snippet_lines = lines[lo - 1 : hi]
    truncated = lo > 1 or hi < total_lines

    return SourceSnippet(
        file_path=relative_path,
        start_line=lo,
        end_line=hi,
        total_lines=total_lines,
        content="\n".join(snippet_lines),
        truncated=truncated,
    )

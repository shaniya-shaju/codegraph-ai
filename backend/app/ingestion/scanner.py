"""Deterministic, non-executing file scanning for imported repositories.

Lists files, hashes them, and buckets them by extension for a
language-composition summary. Never opens a file for anything other than
binary-sniffing or hashing, and never executes, imports, or evaluates
repository content (see SECURITY.md "Parsing safety" — this scanner runs
long before any real parsing exists). Extension-based bucketing is a
statistics label, not language parsing (see AGENTS.md rule 7) — Python
files are the only ones distinguished by a dedicated flag.
"""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}

_LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".cfg": "ini",
    ".ini": "ini",
    ".txt": "text",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".sh": "shell",
    ".sql": "sql",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
}

_KNOWN_BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".bin",
    ".o",
    ".a",
    ".pyc",
    ".pyo",
    ".class",
    ".jar",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".sqlite",
    ".db",
}

_SNIFF_BYTES = 8000
_HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ScannedFile:
    relative_path: str
    size_bytes: int
    language: str
    is_python: bool
    sha256: str


@dataclass
class FileScanResult:
    files: list[ScannedFile] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0
    python_file_count: int = 0
    binary_files_skipped: int = 0
    symlinks_skipped: int = 0
    language_counts: dict[str, int] = field(default_factory=dict)


def _looks_binary(path: Path) -> bool:
    if path.suffix.lower() in _KNOWN_BINARY_EXTENSIONS:
        return True
    try:
        with path.open("rb") as handle:
            chunk = handle.read(_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in chunk


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def scan_repository(root: Path) -> FileScanResult:
    """Recursively scan `root`, applying default ignore rules.

    Does not parse source code — only lists files, hashes them, and
    produces extension-based language statistics.
    """
    result = FileScanResult()
    root = root.resolve()

    for current_dir, subdirs, filenames in os.walk(root):
        current_path = Path(current_dir)
        subdirs[:] = sorted(
            d
            for d in subdirs
            if d not in IGNORED_DIRECTORY_NAMES and not (current_path / d).is_symlink()
        )

        for filename in sorted(filenames):
            file_path = current_path / filename

            if file_path.is_symlink():
                result.symlinks_skipped += 1
                continue

            if _looks_binary(file_path):
                result.binary_files_skipped += 1
                continue

            try:
                size_bytes = file_path.stat().st_size
            except OSError:
                continue

            language = _LANGUAGE_BY_EXTENSION.get(file_path.suffix.lower(), "other")
            is_python = language == "python"

            scanned = ScannedFile(
                relative_path=file_path.relative_to(root).as_posix(),
                size_bytes=size_bytes,
                language=language,
                is_python=is_python,
                sha256=_hash_file(file_path),
            )

            result.files.append(scanned)
            result.total_files += 1
            result.total_bytes += size_bytes
            if is_python:
                result.python_file_count += 1
            result.language_counts[language] = result.language_counts.get(language, 0) + 1

    return result

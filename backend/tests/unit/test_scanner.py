"""Tests for the file-scanning service — see the ingestion task's
"file-scanning service" requirements (list, ignore rules, hash, language
stats; never parses source code)."""

import hashlib
import os
from pathlib import Path

import pytest

from app.ingestion.scanner import scan_repository


def test_scans_files_and_computes_hashes(tmp_path: Path) -> None:
    # write_bytes (not write_text) so content is exact on every platform —
    # Windows text-mode writes would otherwise translate \n to \r\n.
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    (tmp_path / "README.md").write_bytes(b"# hello\n")

    result = scan_repository(tmp_path)

    assert result.total_files == 2
    relative_paths = {f.relative_path for f in result.files}
    assert relative_paths == {"a.py", "README.md"}

    a_py = next(f for f in result.files if f.relative_path == "a.py")
    assert a_py.is_python is True
    assert a_py.language == "python"
    assert a_py.sha256 == hashlib.sha256(b"x = 1\n").hexdigest()

    readme = next(f for f in result.files if f.relative_path == "README.md")
    assert readme.is_python is False
    assert readme.language == "markdown"


def test_ignores_vcs_and_dependency_directories(tmp_path: Path) -> None:
    ignored_dirs = [
        ".git",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "__pycache__",
        "venv",
        ".venv",
    ]
    for dirname in ignored_dirs:
        nested = tmp_path / dirname / "nested"
        nested.mkdir(parents=True)
        (nested / "should_be_ignored.py").write_text("ignored = True\n")

    (tmp_path / "real_module.py").write_text("real = True\n")

    result = scan_repository(tmp_path)

    assert result.total_files == 1
    assert result.files[0].relative_path == "real_module.py"


def test_ignores_binary_files(tmp_path: Path) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    (tmp_path / "unknown_binary.dat").write_bytes(b"abc\x00def\x00ghi")
    (tmp_path / "text.txt").write_text("plain text, no null bytes")

    result = scan_repository(tmp_path)

    assert result.total_files == 1
    assert result.files[0].relative_path == "text.txt"
    assert result.binary_files_skipped == 2


def test_detects_python_files_and_language_stats(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("a = 1\n")
    (tmp_path / "mod2.py").write_text("b = 2\n")
    (tmp_path / "script.js").write_text("const x = 1;\n")
    (tmp_path / "data.json").write_text("{}\n")

    result = scan_repository(tmp_path)

    assert result.python_file_count == 2
    assert result.language_counts["python"] == 2
    assert result.language_counts["javascript"] == 1
    assert result.language_counts["json"] == 1
    assert result.total_files == 4


def test_skips_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("outside data")
    link = tmp_path / "link.txt"

    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this environment.")

    result = scan_repository(tmp_path)

    relative_paths = {f.relative_path for f in result.files}
    assert "link.txt" not in relative_paths
    assert "target.txt" in relative_paths
    assert result.symlinks_skipped == 1


def test_does_not_parse_source_code(tmp_path: Path) -> None:
    """The scanner must never execute or introspect Python source — it only
    hashes bytes and labels by extension."""
    (tmp_path / "bad.py").write_text("raise RuntimeError('should never run')\n")

    result = scan_repository(tmp_path)

    assert result.total_files == 1
    assert result.files[0].is_python is True

"""Tests for safe ZIP extraction — see SECURITY.md "Repository acquisition safety"."""

import io
import stat
import zipfile
from pathlib import Path

import pytest

from app.core.exceptions import PayloadTooLargeError, UnsafeArchiveError, UnsupportedMediaTypeError
from app.ingestion.zip_import import (
    extract_zip_safely,
    is_zip_filename,
    save_upload_within_limit,
)


def _write_zip(
    path: Path, entries: dict[str, bytes], *, symlink_entries: dict[str, str] | None = None
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        for name, target in (symlink_entries or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)


class TestIsZipFilename:
    def test_accepts_dot_zip(self) -> None:
        assert is_zip_filename("archive.zip") is True
        assert is_zip_filename("Archive.ZIP") is True

    def test_rejects_other_extensions(self) -> None:
        assert is_zip_filename("archive.tar.gz") is False
        assert is_zip_filename("notes.txt") is False


class TestSaveUploadWithinLimit:
    def test_writes_all_bytes_when_under_limit(self, tmp_path: Path) -> None:
        source = io.BytesIO(b"a" * 100)
        destination = tmp_path / "upload.zip"

        written = save_upload_within_limit(source, destination, max_bytes=1000)

        assert written == 100
        assert destination.read_bytes() == b"a" * 100

    def test_rejects_oversized_upload_and_removes_partial_file(self, tmp_path: Path) -> None:
        source = io.BytesIO(b"a" * 2000)
        destination = tmp_path / "upload.zip"

        with pytest.raises(PayloadTooLargeError):
            save_upload_within_limit(source, destination, max_bytes=1000)

        assert not destination.exists()


class TestExtractZipSafely:
    def test_extracts_valid_archive(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "valid.zip"
        _write_zip(zip_path, {"README.md": b"hello", "pkg/mod.py": b"x = 1\n"})
        destination = tmp_path / "workspace"
        destination.mkdir()

        extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

        assert (destination / "README.md").read_bytes() == b"hello"
        assert (destination / "pkg" / "mod.py").read_bytes() == b"x = 1\n"

    def test_rejects_non_zip_content(self, tmp_path: Path) -> None:
        fake_zip = tmp_path / "fake.zip"
        fake_zip.write_bytes(b"this is not a zip file")
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(UnsupportedMediaTypeError):
            extract_zip_safely(fake_zip, destination, max_extracted_bytes=1_000_000)

    def test_rejects_path_traversal_entry(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "slip.zip"
        _write_zip(zip_path, {"../evil.txt": b"pwned"})
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(UnsafeArchiveError):
            extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

        assert not (destination.parent / "evil.txt").exists()

    def test_rejects_nested_path_traversal_entry(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "slip2.zip"
        _write_zip(zip_path, {"pkg/../../evil.txt": b"pwned"})
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(UnsafeArchiveError):
            extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

    def test_rejects_absolute_path_entry(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "abs.zip"
        _write_zip(zip_path, {"/etc/passwd": b"root:x:0:0"})
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(UnsafeArchiveError):
            extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

    def test_rejects_symlink_entry(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "symlink.zip"
        _write_zip(zip_path, {"normal.txt": b"hi"}, symlink_entries={"link": "/etc/passwd"})
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(UnsafeArchiveError):
            extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

    def test_rejects_oversized_extracted_content(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "big.zip"
        _write_zip(zip_path, {"big.bin": b"x" * 10_000})
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(PayloadTooLargeError):
            extract_zip_safely(zip_path, destination, max_extracted_bytes=1000)

    def test_ignores_git_directory_entries(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "withgit.zip"
        _write_zip(
            zip_path,
            {
                "README.md": b"hello",
                ".git/HEAD": b"ref: refs/heads/main",
                ".git/objects/aa/bbccdd": b"binarygarbage",
            },
        )
        destination = tmp_path / "workspace"
        destination.mkdir()

        extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

        assert (destination / "README.md").exists()
        assert not (destination / ".git").exists()

    def test_cleanup_after_failed_extraction_leaves_no_partial_files(self, tmp_path: Path) -> None:
        from app.ingestion.workspace import cleanup_workspace

        zip_path = tmp_path / "slip.zip"
        _write_zip(zip_path, {"ok.txt": b"fine", "../evil.txt": b"pwned"})
        destination = tmp_path / "workspace"
        destination.mkdir()

        with pytest.raises(UnsafeArchiveError):
            extract_zip_safely(zip_path, destination, max_extracted_bytes=1_000_000)

        cleanup_workspace(destination)

        assert not destination.exists()

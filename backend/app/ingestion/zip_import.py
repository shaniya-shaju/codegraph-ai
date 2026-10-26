"""Safe ZIP-file import.

Every entry in an uploaded archive is treated as untrusted (see
SECURITY.md). This module never executes, imports, or evaluates anything
it extracts — it only validates paths/types and copies bytes to disk.

Defenses implemented:
  - Only ``.zip``-named uploads are accepted.
  - The raw upload is size-capped while it is being streamed to disk.
  - Every archive member's resolved destination path is verified to stay
    inside the extraction directory (zip-slip / path-traversal / absolute
    path protection).
  - Symlink entries are rejected outright.
  - ``.git``, ``.hg``, ``.svn`` entries are skipped (not extracted).
  - The extracted content is size-capped both from declared metadata
    (fast reject) and from actual bytes written (defends against archives
    with mismatched/lying size metadata).
"""

import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO

from app.core.exceptions import PayloadTooLargeError, UnsafeArchiveError, UnsupportedMediaTypeError

_IGNORED_VCS_DIR_NAMES = {".git", ".hg", ".svn"}
_STREAM_CHUNK_SIZE = 1024 * 1024


def is_zip_filename(filename: str) -> bool:
    return filename.lower().endswith(".zip")


def save_upload_within_limit(source: IO[bytes], destination: Path, *, max_bytes: int) -> int:
    """Stream-copy ``source`` into ``destination``, enforcing ``max_bytes``.

    Raises PayloadTooLargeError (and removes the partial file) if the
    stream exceeds the limit before it ends.
    """
    written = 0
    try:
        with destination.open("wb") as out:
            while chunk := source.read(_STREAM_CHUNK_SIZE):
                written += len(chunk)
                if written > max_bytes:
                    raise PayloadTooLargeError(
                        f"Uploaded file exceeds the configured limit of {max_bytes} bytes."
                    )
                out.write(chunk)
    except PayloadTooLargeError:
        destination.unlink(missing_ok=True)
        raise
    return written


def _is_ignored_vcs_path(member_name: str) -> bool:
    parts = PurePosixPath(member_name).parts
    return any(part in _IGNORED_VCS_DIR_NAMES for part in parts)


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode) if mode else False


def _resolve_safe_path(member_name: str, destination_resolved: Path) -> Path:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise UnsafeArchiveError(f"Absolute paths are not allowed in archives: {member_name!r}")

    candidate = (destination_resolved / normalized).resolve()
    if candidate != destination_resolved and destination_resolved not in candidate.parents:
        raise UnsafeArchiveError(f"Unsafe path in archive (path traversal): {member_name!r}")
    return candidate


def extract_zip_safely(zip_path: Path, destination: Path, *, max_extracted_bytes: int) -> None:
    """Validate and extract a ZIP archive into ``destination``.

    ``destination`` must already exist and be empty. Raises
    UnsupportedMediaTypeError, UnsafeArchiveError, or PayloadTooLargeError
    on any violation; callers are responsible for cleaning up
    ``destination`` on failure (see app.ingestion.workspace).
    """
    if not zipfile.is_zipfile(zip_path):
        raise UnsupportedMediaTypeError("The uploaded file is not a valid ZIP archive.")

    destination_resolved = destination.resolve()

    with zipfile.ZipFile(zip_path) as archive:
        try:
            bad_entry = archive.testzip()
        except OSError as exc:
            raise UnsupportedMediaTypeError("The uploaded ZIP archive is corrupted.") from exc
        if bad_entry is not None:
            raise UnsupportedMediaTypeError(
                f"The uploaded ZIP archive is corrupted (bad entry: {bad_entry!r})."
            )

        members_to_extract: list[tuple[zipfile.ZipInfo, Path]] = []
        declared_total = 0

        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")

            if _is_ignored_vcs_path(normalized):
                continue

            if info.is_dir():
                _resolve_safe_path(normalized, destination_resolved)
                continue

            if _is_symlink_entry(info):
                raise UnsafeArchiveError(
                    f"Symlinks are not allowed in uploaded archives: {info.filename!r}"
                )

            target_path = _resolve_safe_path(normalized, destination_resolved)
            declared_total += info.file_size
            if declared_total > max_extracted_bytes:
                raise PayloadTooLargeError(
                    "The archive's extracted content exceeds the configured size limit."
                )
            members_to_extract.append((info, target_path))

        written_total = 0
        for info, target_path in members_to_extract:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target_path.open("wb") as dest:
                while chunk := source.read(_STREAM_CHUNK_SIZE):
                    written_total += len(chunk)
                    if written_total > max_extracted_bytes:
                        raise PayloadTooLargeError(
                            "The archive's extracted content exceeds the configured size limit."
                        )
                    dest.write(chunk)

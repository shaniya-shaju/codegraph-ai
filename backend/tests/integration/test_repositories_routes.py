"""HTTP-level tests for POST /api/v1/repositories/upload and .../clone."""

import io
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.ingestion import git_clone
from app.main import app

client = TestClient(app)


def _build_zip_bytes(entries: dict[str, bytes], *, compress: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compress) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_upload_valid_zip_is_created_with_file_stats(isolated_database: None) -> None:
    zip_bytes = _build_zip_bytes({"README.md": b"hello", "pkg/mod.py": b"x = 1\n"})

    response = client.post(
        "/api/v1/repositories/upload",
        data={"name": "demo-repo"},
        files={"file": ("demo.zip", zip_bytes, "application/zip")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "zip_upload"
    assert body["file_count"] == 2
    assert body["file_stats"]["total_files"] == 2
    assert body["file_stats"]["python_files"] == 1


def test_upload_rejects_non_zip_extension(isolated_database: None) -> None:
    response = client.post(
        "/api/v1/repositories/upload",
        data={"name": "demo-repo"},
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_upload_rejects_invalid_zip_content(isolated_database: None) -> None:
    response = client.post(
        "/api/v1/repositories/upload",
        data={"name": "demo-repo"},
        files={"file": ("broken.zip", b"not actually a zip", "application/zip")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_upload_rejects_zip_slip(isolated_database: None) -> None:
    zip_bytes = _build_zip_bytes({"../evil.txt": b"pwned"})

    response = client.post(
        "/api/v1/repositories/upload",
        data={"name": "demo-repo"},
        files={"file": ("slip.zip", zip_bytes, "application/zip")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSAFE_ARCHIVE"


def test_upload_rejects_oversized_zip(isolated_database: None) -> None:
    # conftest.py sets INGESTION_MAX_UPLOAD_SIZE_MB=5; ZIP_STORED (no
    # compression) keeps the on-disk archive size close to the raw content
    # size so this reliably exceeds the limit.
    big_payload = b"a" * (6 * 1024 * 1024)
    zip_bytes = _build_zip_bytes({"big.bin": big_payload}, compress=zipfile.ZIP_STORED)

    response = client.post(
        "/api/v1/repositories/upload",
        data={"name": "demo-repo"},
        files={"file": ("big.zip", zip_bytes, "application/zip")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_clone_rejects_invalid_scheme(isolated_database: None) -> None:
    response = client.post(
        "/api/v1/repositories/clone",
        json={"name": "demo", "git_url": "ssh://git@github.com/example/demo.git"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_GIT_URL"


def test_clone_rejects_local_path(isolated_database: None) -> None:
    response = client.post(
        "/api/v1/repositories/clone",
        json={"name": "demo", "git_url": "/etc/passwd"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_GIT_URL"


def test_clone_rejects_disallowed_host(isolated_database: None) -> None:
    # Default REPO_CLONE_ALLOWED_HOSTS is "github.com,gitlab.com" — no env
    # override needed to exercise the default-safe behavior.
    response = client.post(
        "/api/v1/repositories/clone",
        json={"name": "demo", "git_url": "https://evil.com/repo.git"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "GIT_HOST_NOT_ALLOWED"


def test_clone_rejects_when_disabled(
    isolated_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPO_URL_CLONE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/repositories/clone",
            json={"name": "demo", "git_url": "https://github.com/octocat/Hello-World.git"},
        )

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "GIT_CLONING_DISABLED"
    finally:
        get_settings.cache_clear()


def test_clone_allows_custom_host_allowlist(
    isolated_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_git(
        args: list[str], *, cwd: Path | None, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "clone":
            destination = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "README.md").write_text("hello")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "rev-parse" and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(git_clone, "_run_git", fake_run_git)
    monkeypatch.setenv("REPO_CLONE_ALLOWED_HOSTS", "example.com")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/repositories/clone",
            json={"name": "demo", "git_url": "https://example.com/example/repo.git"},
        )

        assert response.status_code == 201, response.text
    finally:
        get_settings.cache_clear()


def test_clone_success_with_mocked_git(
    isolated_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_git(
        args: list[str], *, cwd: Path | None, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "clone":
            destination = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "README.md").write_text("hello")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "rev-parse" and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(git_clone, "_run_git", fake_run_git)

    response = client.post(
        "/api/v1/repositories/clone",
        json={"name": "demo", "git_url": "https://github.com/octocat/Hello-World.git"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "git_url"
    assert body["commit_sha"] == "abc123"
    assert body["default_branch"] == "main"
    assert body["file_stats"]["total_files"] == 1

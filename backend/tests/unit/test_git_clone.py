"""Tests for safe public-HTTPS git cloning — see SECURITY.md
"Repository acquisition safety".

Actual `git` invocations are mocked at the `_run_git` boundary so these
tests are deterministic and require no network access; URL validation is
tested directly since it has no I/O.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.exceptions import (
    GitCloneError,
    GitHostNotAllowedError,
    InvalidGitUrlError,
)
from app.ingestion import git_clone


class TestValidatePublicHttpsUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/octocat/Hello-World.git",
            "https://gitlab.com/group/project.git",
            "https://example.com/repo",
        ],
    )
    def test_accepts_valid_public_https_urls(self, url: str) -> None:
        assert git_clone.validate_public_https_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            "http://github.com/octocat/Hello-World.git",
            "ssh://git@github.com/octocat/Hello-World.git",
            "git@github.com:octocat/Hello-World.git",
            "file:///home/user/repo",
            "/home/user/repo",
            "relative/repo",
            "https://user:pass@github.com/octocat/Hello-World.git",
            "https://localhost/repo.git",
            "https://127.0.0.1/repo.git",
            "https://10.0.0.5/repo.git",
            "https://192.168.1.5/repo.git",
            "https://169.254.1.1/repo.git",
            "https://",
        ],
    )
    def test_rejects_invalid_urls(self, url: str) -> None:
        with pytest.raises(InvalidGitUrlError):
            git_clone.validate_public_https_url(url)


class TestValidateAllowedHost:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/octocat/Hello-World.git",
            "https://gitlab.com/group/project.git",
            "https://GitHub.com/octocat/Hello-World.git",  # case-insensitive
        ],
    )
    def test_accepts_allowed_hosts(self, url: str) -> None:
        git_clone.validate_allowed_host(url, frozenset({"github.com", "gitlab.com"}))

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.com/repo.git",
            "https://bitbucket.org/example/repo.git",
            "https://raw.githubusercontent.com/example/repo",
        ],
    )
    def test_rejects_disallowed_hosts(self, url: str) -> None:
        with pytest.raises(GitHostNotAllowedError):
            git_clone.validate_allowed_host(url, frozenset({"github.com", "gitlab.com"}))

    def test_no_restriction_when_allowed_hosts_empty(self) -> None:
        # None and an empty frozenset both mean "no restriction" — matches
        # clone_repository's default (backward compatible for callers that
        # don't pass allowed_hosts at all).
        git_clone.validate_allowed_host("https://example.com/repo", None)
        git_clone.validate_allowed_host("https://example.com/repo", frozenset())


def _fake_run_git(
    *, commit_sha: str = "abc123", branch: str = "main", extra_bytes: int = 0
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def fake(
        args: list[str], *, cwd: Path | None, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "clone":
            destination = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "README.md").write_text("hello")
            if extra_bytes:
                (destination / "big.bin").write_bytes(b"x" * extra_bytes)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "rev-parse" and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(args, 0, stdout=f"{branch}\n", stderr="")
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout=f"{commit_sha}\n", stderr="")
        raise AssertionError(f"unexpected git invocation: {args}")

    return fake


class TestCloneRepository:
    def test_success_returns_branch_and_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            git_clone, "_run_git", _fake_run_git(commit_sha="deadbeef", branch="main")
        )
        destination = tmp_path / "repo"

        result = git_clone.clone_repository(
            "https://github.com/octocat/Hello-World.git",
            destination=destination,
            timeout_seconds=5,
            max_size_bytes=1_000_000,
        )

        assert result.path == destination
        assert result.branch == "main"
        assert result.commit_sha == "deadbeef"
        assert (destination / "README.md").exists()

    def test_invalid_url_never_invokes_git(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("git must not be invoked for an invalid URL")

        monkeypatch.setattr(git_clone, "_run_git", fail_if_called)

        with pytest.raises(InvalidGitUrlError):
            git_clone.clone_repository(
                "http://github.com/octocat/Hello-World.git",
                destination=tmp_path / "repo",
                timeout_seconds=5,
                max_size_bytes=1_000_000,
            )

    def test_timeout_cleans_up_partial_clone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake(
            args: list[str], *, cwd: Path | None, timeout: int
        ) -> subprocess.CompletedProcess[str]:
            destination = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "partial.txt").write_text("partial")
            raise subprocess.TimeoutExpired(cmd="git", timeout=timeout)

        monkeypatch.setattr(git_clone, "_run_git", fake)
        destination = tmp_path / "repo"

        with pytest.raises(GitCloneError):
            git_clone.clone_repository(
                "https://github.com/octocat/Hello-World.git",
                destination=destination,
                timeout_seconds=1,
                max_size_bytes=1_000_000,
            )

        assert not destination.exists()

    def test_git_failure_cleans_up_partial_clone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake(
            args: list[str], *, cwd: Path | None, timeout: int
        ) -> subprocess.CompletedProcess[str]:
            destination = Path(args[-1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "partial.txt").write_text("partial")
            return subprocess.CompletedProcess(
                args, 128, stdout="", stderr="fatal: repository not found"
            )

        monkeypatch.setattr(git_clone, "_run_git", fake)
        destination = tmp_path / "repo"

        with pytest.raises(GitCloneError):
            git_clone.clone_repository(
                "https://github.com/octocat/Hello-World.git",
                destination=destination,
                timeout_seconds=5,
                max_size_bytes=1_000_000,
            )

        assert not destination.exists()

    def test_disallowed_host_never_invokes_git(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("git must not be invoked for a disallowed host")

        monkeypatch.setattr(git_clone, "_run_git", fail_if_called)

        with pytest.raises(GitHostNotAllowedError):
            git_clone.clone_repository(
                "https://evil.com/repo.git",
                destination=tmp_path / "repo",
                timeout_seconds=5,
                max_size_bytes=1_000_000,
                allowed_hosts=frozenset({"github.com", "gitlab.com"}),
            )

    def test_allowed_host_passes_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(git_clone, "_run_git", _fake_run_git())
        destination = tmp_path / "repo"

        result = git_clone.clone_repository(
            "https://github.com/octocat/Hello-World.git",
            destination=destination,
            timeout_seconds=5,
            max_size_bytes=1_000_000,
            allowed_hosts=frozenset({"github.com", "gitlab.com"}),
        )

        assert result.path == destination

    def test_depth_is_passed_to_git_clone_args(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_args: list[str] = []

        def capturing_run_git(
            args: list[str], *, cwd: Path | None, timeout: int
        ) -> subprocess.CompletedProcess[str]:
            if args[0] == "clone":
                captured_args.extend(args)
                destination = Path(args[-1])
                destination.mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args[0] == "rev-parse" and "--abbrev-ref" in args:
                return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")

        monkeypatch.setattr(git_clone, "_run_git", capturing_run_git)

        git_clone.clone_repository(
            "https://github.com/octocat/Hello-World.git",
            destination=tmp_path / "repo",
            timeout_seconds=5,
            max_size_bytes=1_000_000,
            depth=3,
        )

        assert "--depth" in captured_args
        assert captured_args[captured_args.index("--depth") + 1] == "3"

    def test_oversized_clone_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(git_clone, "_run_git", _fake_run_git(extra_bytes=10_000))
        destination = tmp_path / "repo"

        with pytest.raises(GitCloneError):
            git_clone.clone_repository(
                "https://github.com/octocat/Hello-World.git",
                destination=destination,
                timeout_seconds=5,
                max_size_bytes=1000,
            )

        assert not destination.exists()

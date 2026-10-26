"""Safe public-HTTPS git cloning.

See SECURITY.md "Repository acquisition safety": clones are invoked
without a shell (argument list, never a shell string), are time- and
size-bounded, and this module never executes anything from the cloned
repository — it only runs `git` itself to acquire and inspect metadata.
"""

import ipaddress
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.core.exceptions import GitCloneError, GitHostNotAllowedError, InvalidGitUrlError

_ALLOWED_SCHEME = "https"
_BLOCKED_HOSTNAMES = {"localhost", "0.0.0.0", "::1"}


@dataclass(frozen=True)
class ClonedRepository:
    path: Path
    branch: str
    commit_sha: str


def validate_public_https_url(url: str) -> str:
    """Validate that `url` is a plausible public HTTPS git URL.

    Returns the trimmed URL on success. Raises InvalidGitUrlError for
    non-HTTPS schemes (including SSH/scp-style and file://), local paths,
    embedded credentials, or local/private-network hostnames. This is a
    plausibility check, not a guarantee that the host is truly public.
    """
    trimmed = (url or "").strip()
    if not trimmed:
        raise InvalidGitUrlError("A git URL is required.")

    parts = urlsplit(trimmed)

    if parts.scheme.lower() != _ALLOWED_SCHEME:
        raise InvalidGitUrlError(
            f"Only public HTTPS git URLs are supported (got scheme {parts.scheme!r})."
        )

    if not parts.netloc:
        raise InvalidGitUrlError("Local paths and scheme-less URLs are not supported.")

    if parts.username or parts.password or "@" in parts.netloc:
        raise InvalidGitUrlError("URLs with embedded credentials are not supported.")

    hostname = (parts.hostname or "").lower()
    if not hostname or hostname in _BLOCKED_HOSTNAMES:
        raise InvalidGitUrlError("Cloning from local/loopback hosts is not allowed.")

    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        host_ip = None
    if host_ip is not None and (
        host_ip.is_loopback or host_ip.is_private or host_ip.is_link_local or host_ip.is_reserved
    ):
        raise InvalidGitUrlError("Cloning from local/private network addresses is not allowed.")

    if not parts.path or parts.path == "/":
        raise InvalidGitUrlError("The URL must include a repository path.")

    return trimmed


def validate_allowed_host(url: str, allowed_hosts: frozenset[str] | None) -> None:
    """Raise GitHostNotAllowedError if ``url``'s hostname is not in
    ``allowed_hosts`` (exact match, case-insensitive). ``allowed_hosts``
    being empty/None means no restriction — call only after
    ``validate_public_https_url`` has already confirmed the URL has a
    well-formed public hostname. A narrower, separately-configurable
    layer on top of that general safety check (see
    REPO_CLONE_ALLOWED_HOSTS in .env.example and SECURITY.md) — kept as
    its own function/exception rather than folded into
    validate_public_https_url so the latter's existing, URL-shape-only
    contract and tests are unaffected."""
    if not allowed_hosts:
        return
    hostname = (urlsplit(url).hostname or "").lower()
    if hostname not in allowed_hosts:
        raise GitHostNotAllowedError(
            f"Cloning from {hostname!r} is not allowed. Allowed hosts: "
            f"{', '.join(sorted(allowed_hosts))}."
        )


def _run_git(
    args: list[str], *, cwd: Path | None, timeout: int
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "https"}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _directory_size_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            total += entry.stat().st_size
    return total


def clone_repository(
    url: str,
    *,
    destination: Path,
    branch: str | None = None,
    timeout_seconds: int,
    max_size_bytes: int,
    depth: int = 1,
    allowed_hosts: frozenset[str] | None = None,
) -> ClonedRepository:
    """Shallow-clone a validated public HTTPS repository into ``destination``.

    ``destination`` must not already exist (git creates it). Raises
    InvalidGitUrlError for a rejected URL, GitHostNotAllowedError if
    ``allowed_hosts`` is given and the URL's host isn't in it (git is
    never invoked in either case), or GitCloneError for a timeout, a git
    failure, or a repository that exceeds ``max_size_bytes``. Cleans up
    ``destination`` on any failure after the clone starts.

    ``allowed_hosts`` defaults to None (no restriction) so existing
    callers/tests that don't pass it keep today's behavior unchanged —
    the host allow-list is an additional, separately-configured layer
    (see app.ingestion.service.import_git_repository, which passes the
    real configured allow-list in production).
    """
    validated_url = validate_public_https_url(url)
    validate_allowed_host(validated_url, allowed_hosts)

    clone_args = ["clone", "--depth", str(depth), "--single-branch"]
    if branch:
        clone_args += ["--branch", branch]
    clone_args += [validated_url, str(destination)]

    try:
        result = _run_git(clone_args, cwd=None, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise GitCloneError("Cloning the repository timed out.") from exc

    if result.returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        stderr_lines = result.stderr.strip().splitlines()
        detail = stderr_lines[-1] if stderr_lines else "git clone failed."
        raise GitCloneError(f"Failed to clone repository: {detail}")

    size_bytes = _directory_size_bytes(destination)
    if size_bytes > max_size_bytes:
        shutil.rmtree(destination, ignore_errors=True)
        raise GitCloneError("The cloned repository exceeds the configured size limit.")

    try:
        branch_result = _run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=destination, timeout=timeout_seconds
        )
        commit_result = _run_git(["rev-parse", "HEAD"], cwd=destination, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise GitCloneError("Reading repository metadata timed out.") from exc

    if branch_result.returncode != 0 or commit_result.returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        raise GitCloneError("Failed to read repository metadata after cloning.")

    return ClonedRepository(
        path=destination,
        branch=branch_result.stdout.strip(),
        commit_sha=commit_result.stdout.strip(),
    )

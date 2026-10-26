"""Per-repository_id workspace directories.

See SECURITY.md "Repository acquisition safety": each repository is
ingested into an isolated directory, not a shared scratch space.
"""

import shutil
from pathlib import Path


def allocate_workspace(base_dir: Path, repository_id: str) -> Path:
    """Create and return a fresh, empty workspace directory for one repository_id."""
    base_dir.mkdir(parents=True, exist_ok=True)
    workspace = base_dir / repository_id
    workspace.mkdir(parents=True, exist_ok=False)
    return workspace


def cleanup_workspace(workspace: Path) -> None:
    """Remove a workspace directory (and everything under it), best-effort."""
    shutil.rmtree(workspace, ignore_errors=True)

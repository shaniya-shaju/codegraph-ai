"""Pydantic request/response schemas for the repository import endpoints.

See API_SPEC.md "Repository management" — `/upload` and `/clone` extend
that contract with the response shape below. ``created_at``/
``last_indexed_at`` were added by the frontend-integration task (Prompt
11) so the dashboard/repository-overview pages have what they need — see
that task's "Backend compatibility fixes": purely additive fields on an
existing response model, reusing the already-stored
``RepositoryRecord`` columns (no new business logic).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class LanguageStats(BaseModel):
    """Summary output of app.ingestion.scanner — extension-based counts only,
    never a parse result (see AGENTS.md rule 7/8)."""

    total_files: int
    total_bytes: int
    python_files: int
    binary_files_skipped: int
    languages: dict[str, int]


class RepositoryResponse(BaseModel):
    repository_id: str
    name: str
    source_type: str
    source_location: str
    status: str
    default_branch: str | None = None
    commit_sha: str | None = None
    file_count: int | None = None
    error_message: str | None = None
    # Only populated on the initial upload/clone response — the file scan
    # result (per-language counts) isn't persisted, so list/detail
    # responses always send None here.
    file_stats: LanguageStats | None = None
    created_at: datetime | None = None
    last_indexed_at: datetime | None = None


class CloneRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    git_url: str = Field(min_length=1)
    branch: str | None = None

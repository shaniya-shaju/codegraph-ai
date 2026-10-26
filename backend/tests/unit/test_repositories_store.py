"""Tests for the Repository entity's repository-pattern data access."""

from app.core.database import get_session_factory
from app.domain.repositories.store import (
    create_repository,
    get_repository,
    list_repositories,
    mark_failed,
    mark_ready,
)


def test_create_and_get_repository(isolated_database: None) -> None:
    session = get_session_factory()()
    try:
        record = create_repository(
            session,
            repository_id="repo-1",
            name="demo",
            source_type="zip_upload",
            source_location="demo.zip",
        )

        assert record.status == "pending"

        fetched = get_repository(session, "repo-1")
        assert fetched is not None
        assert fetched.name == "demo"
    finally:
        session.close()


def test_get_repository_returns_none_when_missing(isolated_database: None) -> None:
    session = get_session_factory()()
    try:
        assert get_repository(session, "does-not-exist") is None
    finally:
        session.close()


def test_list_repositories_returns_all_created_records(isolated_database: None) -> None:
    session = get_session_factory()()
    try:
        create_repository(
            session,
            repository_id="repo-a",
            name="a",
            source_type="zip_upload",
            source_location="a.zip",
        )
        create_repository(
            session,
            repository_id="repo-b",
            name="b",
            source_type="git_url",
            source_location="https://github.com/example/b.git",
        )

        results = list_repositories(session)

        assert {r.repository_id for r in results} == {"repo-a", "repo-b"}
    finally:
        session.close()


def test_mark_ready_updates_status_and_file_count(isolated_database: None) -> None:
    session = get_session_factory()()
    try:
        record = create_repository(
            session,
            repository_id="repo-ready",
            name="demo",
            source_type="git_url",
            source_location="https://github.com/example/demo.git",
        )

        updated = mark_ready(
            session, record, file_count=42, commit_sha="abc123", default_branch="main"
        )

        assert updated.status == "ready"
        assert updated.file_count == 42
        assert updated.commit_sha == "abc123"
        assert updated.default_branch == "main"
        assert updated.last_indexed_at is not None
    finally:
        session.close()


def test_mark_failed_updates_status_and_error_message(isolated_database: None) -> None:
    session = get_session_factory()()
    try:
        record = create_repository(
            session,
            repository_id="repo-failed",
            name="demo",
            source_type="zip_upload",
            source_location="demo.zip",
        )

        updated = mark_failed(session, record, error_message="boom")

        assert updated.status == "failed"
        assert updated.error_message == "boom"
    finally:
        session.close()

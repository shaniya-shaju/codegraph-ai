"""Unit tests for app.core.config's repo-root path anchoring.

Covers the same class of bug already fixed for Settings.model_config's
env_file: a relative filesystem-path setting must resolve against the
repository root, not the process's current working directory — otherwise
launching the backend from backend/ (the Makefile's run-backend target)
and running a script from the repo root (demo-seed, tests) silently
disagree about where the SQLite DB / Chroma index / ingestion
directories live.
"""

from app.core.config import _REPO_ROOT, Settings


def test_chroma_persist_directory_anchors_to_repo_root_regardless_of_cwd(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(chroma_persist_directory="./data/chroma")
    assert settings.chroma_persist_directory == str((_REPO_ROOT / "data" / "chroma").resolve())


def test_ingestion_directories_anchor_to_repo_root_regardless_of_cwd(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        ingestion_allowed_base_dir="./data/allowed_repos",
        ingestion_workspace_dir="./data/workspaces",
    )
    assert settings.ingestion_allowed_base_dir == str(
        (_REPO_ROOT / "data" / "allowed_repos").resolve()
    )
    assert settings.ingestion_workspace_dir == str((_REPO_ROOT / "data" / "workspaces").resolve())


def test_relative_path_settings_resolve_identically_from_different_cwds(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    from_tmp_path = Settings(chroma_persist_directory="./data/chroma").chroma_persist_directory

    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    from_other_dir = Settings(chroma_persist_directory="./data/chroma").chroma_persist_directory

    assert from_tmp_path == from_other_dir


def test_absolute_path_settings_pass_through_unchanged(tmp_path) -> None:
    absolute = str(tmp_path / "chroma")
    settings = Settings(chroma_persist_directory=absolute)
    assert settings.chroma_persist_directory == absolute


def test_relative_sqlite_database_url_anchors_to_repo_root(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(database_url="sqlite:///./data/codegraph.db")
    expected = (_REPO_ROOT / "data" / "codegraph.db").resolve().as_posix()
    assert settings.database_url == f"sqlite:///{expected}"


def test_absolute_sqlite_database_url_passes_through_unchanged(tmp_path) -> None:
    absolute = (tmp_path / "codegraph.db").as_posix()
    settings = Settings(database_url=f"sqlite:///{absolute}")
    assert settings.database_url == f"sqlite:///{absolute}"


def test_sqlite_memory_database_url_passes_through_unchanged() -> None:
    settings = Settings(database_url="sqlite:///:memory:")
    assert settings.database_url == "sqlite:///:memory:"


def test_non_sqlite_database_url_passes_through_unchanged() -> None:
    url = "postgresql+psycopg2://user:pass@localhost:5432/codegraph"
    settings = Settings(database_url=url)
    assert settings.database_url == url


def test_repo_clone_allowed_hosts_set_parses_comma_separated_lowercase() -> None:
    settings = Settings(repo_clone_allowed_hosts="GitHub.com, gitlab.com ,,")
    assert settings.repo_clone_allowed_hosts_set == frozenset({"github.com", "gitlab.com"})


def test_repo_clone_allowed_hosts_set_empty_string_means_no_restriction() -> None:
    settings = Settings(repo_clone_allowed_hosts="")
    assert settings.repo_clone_allowed_hosts_set == frozenset()

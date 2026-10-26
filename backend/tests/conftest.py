"""Shared test configuration.

Sets test-scoped environment variable *defaults* before any application
module is imported. Several modules read settings at import time (e.g.
app.api.routes.repositories calls init_db() at module scope), and
app.core.config.get_settings() is cached on first use — so these defaults
must be in place before pytest imports the first test module, which is
exactly what happens here: pytest loads conftest.py (and runs this
module-level code) before collecting/importing any test file.
"""

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

_TEST_DATA_DIR = Path(__file__).resolve().parent / ".test-data"

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TEST_DATA_DIR / 'test.db').as_posix()}")
os.environ.setdefault("INGESTION_WORKSPACE_DIR", str(_TEST_DATA_DIR / "workspaces"))
os.environ.setdefault("INGESTION_ALLOWED_BASE_DIR", str(_TEST_DATA_DIR / "allowed_repos"))
os.environ.setdefault("INGESTION_MAX_UPLOAD_SIZE_MB", "5")
os.environ.setdefault("INGESTION_MAX_REPO_SIZE_MB", "5")
os.environ.setdefault("INGESTION_CLONE_TIMEOUT_SECONDS", "5")
os.environ.setdefault("CHROMA_PERSIST_DIRECTORY", str(_TEST_DATA_DIR / "chroma"))


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_dir() -> Iterator[None]:
    yield
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _fake_embedding_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets a fast, offline, deterministic embedding provider
    by default — never downloads/loads a real sentence-transformers model
    (see the indexing task: "Mock the model in unit tests. Do not
    download a large embedding model during ordinary unit tests.").

    Patches the *singleton instance* `get_embedding_provider()` returns
    (not the factory function itself), so every module that already holds
    a reference to it — app.ingestion.service/analysis,
    api.routes.indexing/health — is covered by this one patch regardless
    of how each imported the factory (see the parallel issue this exact
    pattern avoids: patching a `from X import Y`-style reference only
    affects the module that did the importing, not others).

    Tests that specifically exercise the real SentenceTransformerProvider
    (see tests/unit/indexing/test_sentence_transformer_provider.py) mock
    the underlying model class directly instead and are unaffected by this.
    """
    from app.indexing.sentence_transformer_provider import get_embedding_provider
    from tests.fakes import FakeEmbeddingProvider

    provider = get_embedding_provider()
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr(provider, "embed_documents", fake.embed_documents)
    monkeypatch.setattr(provider, "embed_query", fake.embed_query)
    monkeypatch.setattr(provider, "is_loaded", lambda: True)


@pytest.fixture
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the app at a throwaway SQLite file + workspace dir for one test.

    Use this whenever a test's assertions depend on the *complete* set of
    rows in a table (e.g. listing/counting), where sharing the session-wide
    default test database with other tests would be unreliable.
    """
    from app.core import database
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("INGESTION_WORKSPACE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    database.reset_database_state()
    database.init_db()

    yield

    get_settings.cache_clear()
    database.reset_database_state()

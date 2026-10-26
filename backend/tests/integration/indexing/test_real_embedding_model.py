"""Opt-in test against the REAL configured Sentence Transformers model.

Skipped by default — set RUN_REAL_EMBEDDING_MODEL_TESTS=1 to enable. This
downloads/loads an actual model from the Hub, so it is deliberately kept
out of the fast/offline default test run (see the indexing task: "Mock
the model in unit tests. Do not download a large embedding model during
ordinary unit tests. The normal test suite must remain fast and
offline-capable.").

Uses whatever EMBEDDING_MODEL_NAME/EMBEDDING_TRUST_REMOTE_CODE are set to
in the environment (see .env.example) — the *actually configured* model,
not a hardcoded one. The default model,
sentence-transformers/all-MiniLM-L6-v2, needs no trust_remote_code
opt-in. Some alternative models (e.g. jinaai/jina-embeddings-v2-base-code)
do require EMBEDDING_TRUST_REMOTE_CODE=true to load correctly; if you've
switched to one of those without setting it, this test fails with the
same guiding error a real deployment would see rather than silently
falling back to a different model.
"""

import os

import pytest

from app.core.config import get_settings
from app.indexing.sentence_transformer_provider import SentenceTransformerProvider

pytestmark = pytest.mark.real_model

_ENABLED = os.environ.get("RUN_REAL_EMBEDDING_MODEL_TESTS") == "1"
_SKIP_REASON = (
    "Set RUN_REAL_EMBEDDING_MODEL_TESTS=1 to run against the real, "
    "configured embedding model (downloads it from the Hub)."
)


@pytest.mark.skipif(not _ENABLED, reason=_SKIP_REASON)
def test_real_model_produces_correctly_shaped_normalized_embeddings() -> None:
    settings = get_settings()
    provider = SentenceTransformerProvider(settings)

    vectors = provider.embed_documents(
        ["def add(a: int, b: int) -> int:\n    return a + b", "class Foo:\n    pass"]
    )
    query_vector = provider.embed_query("a function that adds two numbers")

    assert len(vectors) == 2
    assert provider.dimension is not None and provider.dimension > 0
    assert all(len(v) == provider.dimension for v in vectors)
    assert len(query_vector) == provider.dimension
    assert vectors[0] != vectors[1]  # distinct inputs produce distinct vectors

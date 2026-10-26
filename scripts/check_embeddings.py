#!/usr/bin/env python3
"""Real embedding-model smoke test — see Prompt 11.5 "Real embedding smoke
test". Loads the actually-configured embedding model (no mocking/fake
vectors), embeds a tiny code snippet and a query, and verifies the
resulting vectors have matching, expected, finite dimensions.

This downloads the configured model from the Hugging Face Hub on first
run if it isn't already cached locally — see .env.example's EMBEDDINGS
section for size/trust_remote_code implications.

Usage:
    python scripts/check_embeddings.py

Exits 0 on success, 1 on any failure.
"""

import math
import sys
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.indexing.exceptions import EmbeddingProviderError  # noqa: E402
from app.indexing.sentence_transformer_provider import SentenceTransformerProvider  # noqa: E402

_SAMPLE_CODE = "def add(a: int, b: int) -> int:\n    return a + b\n"
_SAMPLE_QUERY = "a function that adds two numbers"


def main() -> int:
    settings = get_settings()
    print("CodeGraph AI — embedding model check")
    print(f"Model: {settings.embedding_model_name}")
    print(f"Device: {settings.embedding_device}")
    print(f"trust_remote_code: {settings.embedding_trust_remote_code}")
    print()

    provider = SentenceTransformerProvider(settings)

    started = time.monotonic()
    try:
        document_vectors = provider.embed_documents([_SAMPLE_CODE])
    except EmbeddingProviderError as exc:
        print("[FAIL] load + embed document")
        print(f"Reason: {exc}")
        return 1
    load_and_embed_ms = int((time.monotonic() - started) * 1000)
    print(f"[PASS] load + embed document ({load_and_embed_ms}ms)")

    try:
        query_vector = provider.embed_query(_SAMPLE_QUERY)
    except EmbeddingProviderError as exc:
        print("[FAIL] embed query")
        print(f"Reason: {exc}")
        return 1
    print("[PASS] embed query")

    document_vector = document_vectors[0]
    if len(document_vector) != len(query_vector):
        print("[FAIL] matching dimensions")
        print(f"Reason: document={len(document_vector)} vs query={len(query_vector)}")
        return 1
    print(f"[PASS] matching dimensions (dimension={len(document_vector)})")

    if not all(math.isfinite(v) for v in document_vector + query_vector):
        print("[FAIL] finite values")
        print("Reason: at least one embedding component is NaN/inf.")
        return 1
    print("[PASS] finite values")

    print()
    print(f"Model: {provider.model_name}")
    print(f"Dimension: {provider.dimension}")
    print(f"Device: {settings.embedding_device}")
    print()
    print("Embedding model is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

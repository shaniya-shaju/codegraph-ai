"""The shared embedding-output validation helper every provider uses."""

import pytest

from app.indexing.embedding_provider import validate_embeddings
from app.indexing.exceptions import EmbeddingProviderError


def test_accepts_matching_non_empty_vectors() -> None:
    validate_embeddings(["a", "b"], [[0.1, 0.2], [0.3, 0.4]])


def test_rejects_vector_count_mismatch() -> None:
    with pytest.raises(EmbeddingProviderError):
        validate_embeddings(["a", "b"], [[0.1, 0.2]])


def test_rejects_empty_vector() -> None:
    with pytest.raises(EmbeddingProviderError):
        validate_embeddings(["a"], [[]])


def test_empty_input_and_output_is_valid() -> None:
    validate_embeddings([], [])

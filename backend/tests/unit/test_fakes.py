"""Unit tests for tests/fakes.py's FakeEmbeddingProvider.

Regression coverage for two bugs found while diagnosing
test_unresolvable_symbol_abstains_without_calling_the_llm (see
tests/integration/rag/test_answer_service_integration.py):

1. Byte values were mapped to [0.0, 1.0], confining every fake vector to
   the same hyperoctant — any two *unrelated* texts got a systematic,
   strongly positive cosine similarity regardless of content.
2. The digest was tiled (repeated) to fill `dimension` rather than
   derived from independent hash blocks — tiling scales the dot product
   and both vector norms by the same factor, which cancels out, so
   cosine similarity was mathematically identical to the 32-byte case no
   matter how large `dimension` was set. Increasing `dimension` alone
   did nothing to reduce incidental similarity between unrelated texts.

Together these meant a semantically nonsense query could coincidentally
score as "moderately relevant" against unrelated real code purely by
chance, defeating the one thing a fake embedding provider most needs for
abstention/relevance-threshold tests: unrelated text should score low.
"""

import math

from tests.fakes import FakeEmbeddingProvider


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_vectors_are_within_the_expected_symmetric_range() -> None:
    provider = FakeEmbeddingProvider()
    vector = provider.embed_query("def login(email, password): ...")
    assert all(-1.0 <= value <= 1.0 for value in vector)
    # Not confined to a single sign — a provider whose components were
    # all >= 0 would put every vector in the same hyperoctant.
    assert any(value < 0 for value in vector)
    assert any(value > 0 for value in vector)


def test_embedding_is_deterministic_for_the_same_text() -> None:
    provider = FakeEmbeddingProvider()
    assert provider.embed_query("identical text") == provider.embed_query("identical text")


def test_dimension_is_not_a_tiled_repeat_of_the_same_hash_block() -> None:
    """Pins bug #2: a 384-dim vector must not just be a 32-byte SHA-256
    digest repeated 12 times — that would make cosine similarity between
    any two texts identical to what it'd be at dimension=32."""
    provider = FakeEmbeddingProvider(dimension=384)
    vector = provider.embed_query("some representative source code text")
    first_block = vector[:32]
    second_block = vector[32:64]
    assert first_block != second_block


def test_unrelated_text_scores_low_similarity_against_real_code() -> None:
    """Pins bug #1 + #2 together: a nonsense query must not coincidentally
    clear a moderate relevance threshold (~0.15-0.4, see config.py's
    answer_min_evidence_relevance/answer_medium_confidence_threshold)
    against real, unrelated code — this is exactly the property the
    abstention integration test depends on."""
    provider = FakeEmbeddingProvider()
    query_vector = provider.embed_query("Explain totally_nonexistent_symbol_xyz().")
    code_vector = provider.embed_documents(
        [
            "def find_by_email(email: str) -> dict:\n    return {}",
            "class UserRepository:\n    def save(self, user): ...",
            "def create_access_token(user_id: str) -> str: ...",
        ]
    )
    similarities = [_cosine_similarity(query_vector, v) for v in code_vector]
    assert all(abs(score) < 0.15 for score in similarities), similarities

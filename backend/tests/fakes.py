"""Shared test doubles used across unit and integration tests.

Not a test module itself (no ``test_`` prefix, so pytest won't collect it).
"""

import hashlib
from collections.abc import AsyncIterator
from typing import Any


class FakeEmbeddingProvider:
    """Deterministic, offline, instant embedding provider.

    No ML library, no network call, no model download — same text always
    produces the same vector (derived from its SHA-256 hash). See the
    indexing task: "Integration tests may use a deterministic fake
    embedding provider to avoid downloading a model" / "Mock the model in
    unit tests. Do not download a large embedding model during ordinary
    unit tests."

    Byte values are mapped to [-1.0, 1.0], not [0.0, 1.0] — every
    component confined to a single sign would put every fake vector in
    the same hyperoctant, giving any two *unrelated* texts a systematic,
    strongly positive cosine similarity regardless of content (Chroma is
    configured for cosine distance — see chroma_store.py). Centering
    components around zero keeps unrelated texts' similarity near zero,
    the way real sentence embeddings behave, while identical/near-
    identical text still hashes to an identical/near-identical vector.

    The default dimension (384, matching the real default production
    model's output size — see config.py's EMBEDDING_MODEL_NAME) also
    matters here, not just the sign: incidental cosine similarity between
    two *unrelated* random vectors shrinks roughly as 1/sqrt(dimension),
    so a too-low dimension can still let unrelated text coincidentally
    clear a relevance threshold by chance alone, even with zero-mean
    components.
    """

    def __init__(
        self, *, model_name: str = "fake-test-embedding-model", dimension: int = 384
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int | None:
        return self._dimension

    def is_loaded(self) -> bool:
        return True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        # Each 32-byte block comes from hashing a *different* input
        # (text + its block index) — tiling the same digest repeatedly
        # would make cosine similarity identical to the 32-byte case
        # regardless of `dimension` (tiling scales the dot product and
        # both norms by the same factor, which cancels out), defeating
        # the whole point of a larger dimension reducing incidental
        # similarity variance between unrelated texts.
        raw: list[int] = []
        block = 0
        while len(raw) < self._dimension:
            digest = hashlib.sha256(f"{text}:{block}".encode()).digest()
            raw.extend(digest)
            block += 1
        return [(byte / 127.5) - 1.0 for byte in raw[: self._dimension]]


class FakeAnswerLLMProvider:
    """Deterministic, offline stand-in for app.rag.llm_provider.AnswerLLMProvider
    — see the answer-generation task: "Use fake LLM providers in normal
    tests. No external model calls in the ordinary test suite."

    Configure exactly one of ``structured_result``/``structured_error``
    for the non-streaming path, and/or ``stream_chunks``/``stream_error``
    for the streaming path — whichever the test under test calls.
    """

    def __init__(
        self,
        *,
        structured_result: Any = None,
        structured_error: Exception | None = None,
        stream_chunks: list[str] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self._structured_result = structured_result
        self._structured_error = structured_error
        self._stream_chunks = stream_chunks or []
        self._stream_error = stream_error
        self.generate_structured_calls: list[dict[str, str]] = []
        self.generate_text_stream_calls: list[dict[str, str]] = []

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, output_schema: type
    ) -> Any:
        self.generate_structured_calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt}
        )
        if self._structured_error is not None:
            raise self._structured_error
        return self._structured_result

    async def generate_text_stream(
        self, *, system_prompt: str, user_prompt: str
    ) -> AsyncIterator[str]:
        self.generate_text_stream_calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt}
        )
        if self._stream_error is not None:
            raise self._stream_error
        for chunk in self._stream_chunks:
            yield chunk

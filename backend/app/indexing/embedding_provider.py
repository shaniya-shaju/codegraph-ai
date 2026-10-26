"""Embedding-provider interface.

app.indexing.indexing_service and app.indexing.retrieval_service only ever
depend on this Protocol — never on ``sentence_transformers`` (or any other
concrete library) directly, so a future Ollama / OpenAI-compatible
provider is a drop-in replacement (see the indexing task's "Make the
provider replaceable later").
"""

from typing import Protocol, runtime_checkable

from app.indexing.exceptions import EmbeddingProviderError


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int | None:
        """The embedding vector size, once known (None before the model
        has been loaded — see sentence_transformer_provider.py's lazy
        loading)."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def is_loaded(self) -> bool:
        """Whether the underlying model is already loaded in memory —
        never triggers a load itself (see the integration-reliability
        task's "Lazy embedding model behavior": "`/health/live` must
        never trigger model loading.")."""
        ...


def validate_embeddings(texts: list[str], vectors: list[list[float]]) -> None:
    """Shared validation every concrete provider should apply to its own
    output before returning it — see the interface's "Validate that
    returned vector counts match input counts" / "Reject empty vectors"."""
    if len(vectors) != len(texts):
        raise EmbeddingProviderError(
            f"Embedding provider returned {len(vectors)} vectors for {len(texts)} inputs."
        )
    for index, vector in enumerate(vectors):
        if not vector:
            raise EmbeddingProviderError(
                f"Embedding provider returned an empty vector at index {index}."
            )

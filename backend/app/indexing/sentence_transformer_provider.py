"""Local sentence-transformers embedding provider.

Runs entirely on this machine — see SECURITY.md and AGENTS.md rule 11/12:
no repository source code is ever sent to an external API by this
provider. The only network activity is a one-time model download from
the Hugging Face Hub on first use if the model isn't already cached
locally (standard `sentence-transformers` / `huggingface_hub` behavior),
never a per-request call.

Model licensing/operational note: the default model
(``sentence-transformers/all-MiniLM-L6-v2``) ships no custom Hub code and
never needs it. Some alternative models — e.g.
``jinaai/jina-embeddings-v2-base-code``, previously this project's
default — do ship custom modeling code on the Hub and require
``trust_remote_code=True`` to load correctly. This provider never enables
that silently — see ``Settings.embedding_trust_remote_code`` (defaults to
False) and SECURITY.md. Loading such a model with
``trust_remote_code=False`` does not always fail loudly: depending on theHS
installed ``transformers`` version it can silently fall back to a
generic architecture with some layers randomly initialized rather than
loaded from the real checkpoint — see docs/TROUBLESHOOTING.md
"trust_remote_code problem" before switching to one.
"""

import logging
import time
from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING

from app.core.config import Settings, get_settings
from app.indexing.embedding_provider import validate_embeddings
from app.indexing.exceptions import EmbeddingProviderError

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class SentenceTransformerProvider:
    """Loads its model lazily (on first embed call), once, behind a lock —
    never re-loaded per request (see the indexing task's "Avoid loading
    the model separately for every request")."""

    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.embedding_model_name
        self._device = settings.embedding_device
        self._batch_size = settings.embedding_batch_size
        self._normalize = settings.embedding_normalize
        self._max_sequence_length = settings.embedding_max_sequence_length
        self._trust_remote_code = settings.embedding_trust_remote_code
        self._model: SentenceTransformer | None = None
        self._dimension: int | None = None
        self._load_lock = Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int | None:
        return self._dimension

    def is_loaded(self) -> bool:
        """For readiness checks — never triggers a load (see health.py's
        "Avoid forcing expensive model loading on every lightweight
        liveness request")."""
        return self._model is not None

    def _ensure_loaded(self) -> "SentenceTransformer":
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is None:
                self._model = self._load_model()
            return self._model

    def _load_model(self) -> "SentenceTransformer":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency is required, defensive only
            raise EmbeddingProviderError(
                "The sentence-transformers package is not installed."
            ) from exc

        started = time.monotonic()
        try:
            model = SentenceTransformer(
                self._model_name,
                device=self._device,
                trust_remote_code=self._trust_remote_code,
            )
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Failed to load embedding model {self._model_name!r} ({exc.__class__.__name__}). "
                "If this model requires custom code on the Hub (e.g. "
                "jinaai/jina-embeddings-v2-base-code), set "
                "EMBEDDING_TRUST_REMOTE_CODE=true explicitly — it is never enabled "
                "automatically. See SECURITY.md."
            ) from exc

        if self._max_sequence_length:
            model.max_seq_length = self._max_sequence_length

        self._dimension = model.get_sentence_embedding_dimension()
        duration_ms = int((time.monotonic() - started) * 1000)
        # Model name/device only — never log input text (SECURITY.md: "Do
        # not log complete source-code chunks at normal log levels").
        logger.info(
            "Loaded embedding model %r on device=%s in %dms (dimension=%s)",
            self._model_name,
            self._device,
            duration_ms,
            self._dimension,
        )
        return model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
            
        model = self._ensure_loaded()
        model.max_seq_length = 512
        try:
            raw_vectors = model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=self._normalize,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            logger.exception(
                "SentenceTransformer encode failed: model=%s, device=%s, batch_size=%s",
                self._model_name,
                self._device,
                self._batch_size,
            )
            raise EmbeddingProviderError(
                f"Embedding generation failed: {exc.__class__.__name__}"
            ) from exc

        vectors = [vector.tolist() for vector in raw_vectors]
        validate_embeddings(texts, vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingProviderError("Cannot embed an empty query.")
        return self.embed_documents([text])[0]


@lru_cache
def get_embedding_provider() -> SentenceTransformerProvider:
    """Cached provider accessor — the model loads lazily on first embed
    call, not here (see the class's own lazy-loading docstring)."""
    return SentenceTransformerProvider(get_settings())


def reset_embedding_provider() -> None:
    """Test-only: clear the cached provider so the next
    ``get_embedding_provider()`` builds a fresh one against current settings."""
    get_embedding_provider.cache_clear()

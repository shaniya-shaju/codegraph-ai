"""SentenceTransformerProvider: lazy loading, batching, normalization,
validation, and controlled failure — the underlying `SentenceTransformer`
model class is always mocked here (never a real download; see the
indexing task: "Mock the model in unit tests")."""

import numpy as np
import pytest

from app.core.config import Settings
from app.indexing.exceptions import EmbeddingProviderError
from app.indexing.sentence_transformer_provider import SentenceTransformerProvider


class _FakeSentenceTransformer:
    """Records every constructor/encode call for assertions."""

    instances: list["_FakeSentenceTransformer"] = []

    def __init__(
        self, model_name: str, device: str | None = None, trust_remote_code: bool = False
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.trust_remote_code = trust_remote_code
        self.max_seq_length = 256
        self.encode_calls: list[dict[str, object]] = []
        _FakeSentenceTransformer.instances.append(self)

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool,
    ) -> np.ndarray:
        self.encode_calls.append(
            {
                "texts": list(texts),
                "batch_size": batch_size,
                "normalize_embeddings": normalize_embeddings,
            }
        )
        return np.array([[float(i)] * 4 for i in range(len(texts))], dtype="float32")


@pytest.fixture(autouse=True)
def _reset_fake_instances() -> None:
    _FakeSentenceTransformer.instances.clear()


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def _patch_model_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", _FakeSentenceTransformer)


class TestLazyLoading:
    def test_model_is_not_loaded_at_construction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        assert provider.is_loaded() is False
        assert _FakeSentenceTransformer.instances == []

    def test_first_embed_call_loads_the_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        provider.embed_documents(["hello"])

        assert provider.is_loaded() is True
        assert len(_FakeSentenceTransformer.instances) == 1

    def test_model_loaded_only_once_across_multiple_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        provider.embed_documents(["a"])
        provider.embed_documents(["b"])
        provider.embed_query("c")

        assert len(_FakeSentenceTransformer.instances) == 1

    def test_empty_document_list_never_triggers_a_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        result = provider.embed_documents([])

        assert result == []
        assert provider.is_loaded() is False


class TestDocumentAndQueryPaths:
    def test_embed_documents_returns_one_vector_per_input(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        vectors = provider.embed_documents(["a", "b", "c"])

        assert len(vectors) == 3
        assert all(len(v) == 4 for v in vectors)

    def test_embed_query_returns_a_single_vector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        vector = provider.embed_query("hello")

        assert len(vector) == 4

    def test_embed_query_rejects_empty_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        with pytest.raises(EmbeddingProviderError):
            provider.embed_query("   ")


class TestBatchingAndNormalization:
    def test_batch_size_from_settings_is_passed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings(embedding_batch_size=7))

        provider.embed_documents(["a"])

        call = _FakeSentenceTransformer.instances[0].encode_calls[0]
        assert call["batch_size"] == 7

    def test_normalize_true_is_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings(embedding_normalize=True))

        provider.embed_documents(["a"])

        call = _FakeSentenceTransformer.instances[0].encode_calls[0]
        assert call["normalize_embeddings"] is True

    def test_normalize_false_is_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings(embedding_normalize=False))

        provider.embed_documents(["a"])

        call = _FakeSentenceTransformer.instances[0].encode_calls[0]
        assert call["normalize_embeddings"] is False


class TestValidation:
    def test_vector_count_mismatch_raises_a_controlled_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BrokenModel(_FakeSentenceTransformer):
            def encode(self, texts, **kwargs):  # type: ignore[override]
                return np.array(
                    [[1.0, 2.0, 3.0, 4.0]]
                )  # always 1 vector, regardless of input count

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", _BrokenModel)
        provider = SentenceTransformerProvider(_settings())

        with pytest.raises(EmbeddingProviderError):
            provider.embed_documents(["a", "b"])


class TestControlledFailure:
    def test_model_load_failure_raises_embedding_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: object, **kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", _raise)
        provider = SentenceTransformerProvider(_settings())

        with pytest.raises(EmbeddingProviderError):
            provider.embed_documents(["a"])

    def test_trust_remote_code_defaults_to_false_and_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_model_class(monkeypatch)
        provider = SentenceTransformerProvider(_settings())

        provider.embed_documents(["a"])

        assert _FakeSentenceTransformer.instances[0].trust_remote_code is False

    def test_encode_failure_raises_a_controlled_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _EncodeFails(_FakeSentenceTransformer):
            def encode(self, texts, **kwargs):  # type: ignore[override]
                raise RuntimeError("device error")

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", _EncodeFails)
        provider = SentenceTransformerProvider(_settings())

        with pytest.raises(EmbeddingProviderError):
            provider.embed_documents(["a"])

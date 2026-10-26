"""Unit tests for app.core.dependencies.status_service — every dependency
faked/stubbed, no real database/Neo4j/Chroma/model/LLM server needed."""

import httpx
import pytest

from app.core.config import Settings
from app.core.database import get_engine
from app.core.dependencies.circuit_breaker import CircuitState
from app.core.dependencies.models import DependencyStatus
from app.core.dependencies.status_service import (
    check_chroma,
    check_database,
    check_embedding_provider,
    check_llm,
    check_neo4j,
    get_readiness_report,
)


class _FakeNeo4jClient:
    def __init__(self, *, circuit_state: CircuitState, reachable: bool) -> None:
        self.circuit_state = circuit_state
        self._reachable = reachable

    def verify_connectivity(self) -> bool:
        return self._reachable


class _FakeVectorStore:
    def __init__(self, status: str = "ok") -> None:
        self._status = status

    def health_check(self) -> str:
        return self._status


class _FakeEmbeddingProvider:
    def __init__(self, *, loaded: bool, model_name: str = "fake/embedding-model") -> None:
        self._loaded = loaded
        self.model_name = model_name

    def is_loaded(self) -> bool:
        return self._loaded


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class TestCheckDatabase:
    def test_ready_when_query_succeeds(self) -> None:
        state = check_database(get_engine())
        assert state.status is DependencyStatus.READY


class TestCheckNeo4j:
    def test_ready_when_reachable(self) -> None:
        client = _FakeNeo4jClient(circuit_state=CircuitState.CLOSED, reachable=True)
        state = check_neo4j(client)  # type: ignore[arg-type]
        assert state.status is DependencyStatus.READY

    def test_unavailable_when_unreachable(self) -> None:
        client = _FakeNeo4jClient(circuit_state=CircuitState.CLOSED, reachable=False)
        state = check_neo4j(client)  # type: ignore[arg-type]
        assert state.status is DependencyStatus.UNAVAILABLE

    def test_unavailable_without_touching_the_client_when_circuit_open(self) -> None:
        class _NeverCall(_FakeNeo4jClient):
            def verify_connectivity(self) -> bool:
                raise AssertionError("must not be called while the circuit is open")

        client = _NeverCall(circuit_state=CircuitState.OPEN, reachable=True)
        state = check_neo4j(client)  # type: ignore[arg-type]
        assert state.status is DependencyStatus.UNAVAILABLE


class TestCheckChroma:
    def test_ready_when_ok(self) -> None:
        state = check_chroma(_FakeVectorStore("ok"))  # type: ignore[arg-type]
        assert state.status is DependencyStatus.READY

    def test_unavailable_otherwise(self) -> None:
        state = check_chroma(_FakeVectorStore("unavailable"))  # type: ignore[arg-type]
        assert state.status is DependencyStatus.UNAVAILABLE


class TestCheckEmbeddingProvider:
    def test_not_loaded_before_first_use(self) -> None:
        state = check_embedding_provider(_FakeEmbeddingProvider(loaded=False))  # type: ignore[arg-type]
        assert state.status is DependencyStatus.NOT_LOADED

    def test_ready_once_loaded(self) -> None:
        state = check_embedding_provider(_FakeEmbeddingProvider(loaded=True))  # type: ignore[arg-type]
        assert state.status is DependencyStatus.READY

    def test_reports_the_configured_model_name(self) -> None:
        state = check_embedding_provider(
            _FakeEmbeddingProvider(loaded=True, model_name="jinaai/jina-embeddings-v2-base-code")  # type: ignore[arg-type]
        )
        assert state.model == "jinaai/jina-embeddings-v2-base-code"


class TestCheckLlmAnthropic:
    """The cloud ("anthropic") path never makes a live network call — see
    check_llm's docstring."""

    def test_not_configured_with_placeholder_api_key(self) -> None:
        state = check_llm(_settings(llm_provider="anthropic", llm_api_key="changeme"))
        assert state.status is DependencyStatus.NOT_LOADED
        assert state.detail == "not_configured"
        assert state.provider == "anthropic"

    def test_not_configured_with_empty_model(self) -> None:
        state = check_llm(_settings(llm_provider="anthropic", llm_api_key="sk-real", llm_model=""))
        assert state.status is DependencyStatus.NOT_LOADED

    def test_ready_when_a_real_looking_key_and_model_are_present(self) -> None:
        state = check_llm(
            _settings(llm_provider="anthropic", llm_api_key="sk-real", llm_model="claude-sonnet-5")
        )
        assert state.status is DependencyStatus.READY
        assert state.detail == "not_verified_live"
        assert state.model == "claude-sonnet-5"


class TestCheckLlmOpenAiCompatible:
    """Covers both "openai_compatible" and its "lmstudio" alias."""

    @pytest.mark.parametrize("provider_value", ["openai_compatible", "lmstudio", "LMStudio"])
    def test_not_configured_without_base_url(self, provider_value: str) -> None:
        state = check_llm(_settings(llm_provider=provider_value, llm_base_url=None))
        assert state.status is DependencyStatus.NOT_LOADED
        assert state.detail == "not_configured"
        assert state.provider == "openai_compatible"

    def test_not_configured_without_model(self) -> None:
        state = check_llm(
            _settings(
                llm_provider="lmstudio",
                llm_base_url="http://localhost:1234/v1",
                llm_model="",
            )
        )
        assert state.status is DependencyStatus.NOT_LOADED

    def test_unavailable_when_the_server_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "get", _raise_connect_error)
        state = check_llm(
            _settings(
                llm_provider="lmstudio",
                llm_base_url="http://localhost:1234/v1",
                llm_model="llama-3.1-8b",
            )
        )
        assert state.status is DependencyStatus.UNAVAILABLE
        assert state.detail == "ConnectError"

    def test_ready_when_the_configured_model_is_in_the_served_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_get(url: str, **kwargs: object) -> httpx.Response:
            assert url == "http://localhost:1234/v1/models"
            return httpx.Response(
                200,
                json={"data": [{"id": "llama-3.1-8b"}, {"id": "other"}]},
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx, "get", _fake_get)
        state = check_llm(
            _settings(
                llm_provider="lmstudio",
                llm_base_url="http://localhost:1234/v1",
                llm_model="llama-3.1-8b",
            )
        )
        assert state.status is DependencyStatus.READY

    def test_unavailable_when_the_configured_model_is_not_currently_served(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [{"id": "some-other-model"}]}, request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(httpx, "get", _fake_get)
        state = check_llm(
            _settings(
                llm_provider="lmstudio",
                llm_base_url="http://localhost:1234/v1",
                llm_model="llama-3.1-8b",
            )
        )
        assert state.status is DependencyStatus.UNAVAILABLE
        assert state.detail == "configured_model_not_served"

    def test_ready_when_the_server_does_not_expose_a_model_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A minimal/older OpenAI-compatible server that returns an empty
        model list is treated as reachable, not as "wrong model" — we
        only compare against the served list when it's non-empty."""

        def _fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", _fake_get)
        state = check_llm(
            _settings(
                llm_provider="lmstudio",
                llm_base_url="http://localhost:1234/v1",
                llm_model="llama-3.1-8b",
            )
        )
        assert state.status is DependencyStatus.READY


class TestGetReadinessReport:
    def test_all_ready_or_not_loaded_is_ready_overall(self) -> None:
        report = get_readiness_report(
            engine=get_engine(),
            neo4j_client=_FakeNeo4jClient(circuit_state=CircuitState.CLOSED, reachable=True),  # type: ignore[arg-type]
            vector_store=_FakeVectorStore("ok"),  # type: ignore[arg-type]
            embedding_provider=_FakeEmbeddingProvider(loaded=False),  # type: ignore[arg-type]
            settings=_settings(),
        )
        assert report.status == "ready"
        assert "llm" in report.dependencies

    def test_neo4j_unavailable_is_degraded_not_unavailable(self) -> None:
        report = get_readiness_report(
            engine=get_engine(),
            neo4j_client=_FakeNeo4jClient(circuit_state=CircuitState.OPEN, reachable=False),  # type: ignore[arg-type]
            vector_store=_FakeVectorStore("ok"),  # type: ignore[arg-type]
            embedding_provider=_FakeEmbeddingProvider(loaded=False),  # type: ignore[arg-type]
            settings=_settings(),
        )
        assert report.status == "degraded"
        assert report.dependencies["neo4j"].status is DependencyStatus.UNAVAILABLE

    def test_llm_not_configured_does_not_degrade_overall_status(self) -> None:
        report = get_readiness_report(
            engine=get_engine(),
            neo4j_client=_FakeNeo4jClient(circuit_state=CircuitState.CLOSED, reachable=True),  # type: ignore[arg-type]
            vector_store=_FakeVectorStore("ok"),  # type: ignore[arg-type]
            embedding_provider=_FakeEmbeddingProvider(loaded=False),  # type: ignore[arg-type]
            settings=_settings(llm_provider="anthropic", llm_api_key="changeme"),
        )
        assert report.status == "ready"
        assert report.dependencies["llm"].status is DependencyStatus.NOT_LOADED

    def test_never_exposes_credentials_or_paths_in_detail(self) -> None:
        report = get_readiness_report(
            engine=get_engine(),
            neo4j_client=_FakeNeo4jClient(circuit_state=CircuitState.CLOSED, reachable=True),  # type: ignore[arg-type]
            vector_store=_FakeVectorStore("ok"),  # type: ignore[arg-type]
            embedding_provider=_FakeEmbeddingProvider(loaded=False),  # type: ignore[arg-type]
            settings=_settings(llm_api_key="sk-super-secret-value", llm_model="claude-sonnet-5"),
        )
        for state in report.dependencies.values():
            if state.detail:
                assert "://" not in state.detail
                assert "password" not in state.detail.lower()
                assert "sk-super-secret-value" not in state.detail

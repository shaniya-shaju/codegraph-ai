"""Neo4jClient: connectivity, transaction helpers, and clear failure when
Neo4j is unreachable — see the graph task's "The application should fail
clearly when Neo4j is required but unavailable." No real Neo4j needed:
the underlying `neo4j.GraphDatabase.driver` / session are mocked."""

from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.core.config import Settings
from app.graph.exceptions import Neo4jConnectionError, Neo4jQueryError
from app.graph.neo4j_client import Neo4jClient


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


class TestVerifyConnectivity:
    def test_returns_true_when_driver_reports_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_driver = MagicMock()
        fake_driver.verify_connectivity.return_value = None
        monkeypatch.setattr(
            "app.graph.neo4j_client.GraphDatabase.driver", lambda *a, **k: fake_driver
        )

        client = Neo4jClient(_settings())

        assert client.verify_connectivity() is True
        assert client.health_status() == "ok"

    def test_returns_false_when_driver_reports_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_driver = MagicMock()
        fake_driver.verify_connectivity.side_effect = ServiceUnavailable("down")
        monkeypatch.setattr(
            "app.graph.neo4j_client.GraphDatabase.driver", lambda *a, **k: fake_driver
        )

        client = Neo4jClient(_settings())

        assert client.verify_connectivity() is False
        assert client.health_status() == "unavailable"

    def test_never_raises_even_on_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_driver = MagicMock()
        fake_driver.verify_connectivity.side_effect = AuthError("bad credentials")
        monkeypatch.setattr(
            "app.graph.neo4j_client.GraphDatabase.driver", lambda *a, **k: fake_driver
        )

        client = Neo4jClient(_settings())

        assert client.verify_connectivity() is False


class TestExecuteWriteFailureTranslation:
    def test_service_unavailable_becomes_neo4j_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_driver = MagicMock()
        fake_driver.session.side_effect = ServiceUnavailable("down")
        monkeypatch.setattr(
            "app.graph.neo4j_client.GraphDatabase.driver", lambda *a, **k: fake_driver
        )

        client = Neo4jClient(_settings())

        with pytest.raises(Neo4jConnectionError):
            client.execute_write("MERGE (n:X {id: $id})", {"id": "1"})

    def test_query_error_becomes_neo4j_query_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from neo4j.exceptions import ClientError

        fake_session = MagicMock()
        fake_session.__enter__.return_value = fake_session
        fake_session.__exit__.return_value = False
        fake_session.execute_write.side_effect = ClientError("bad cypher")

        fake_driver = MagicMock()
        fake_driver.session.return_value = fake_session
        monkeypatch.setattr(
            "app.graph.neo4j_client.GraphDatabase.driver", lambda *a, **k: fake_driver
        )

        client = Neo4jClient(_settings())

        with pytest.raises(Neo4jQueryError):
            client.execute_write("NOT VALID CYPHER", {})


class TestCredentialsNeverLeak:
    def test_connection_error_message_does_not_contain_the_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_driver = MagicMock()
        fake_driver.session.side_effect = ServiceUnavailable("down")
        monkeypatch.setattr(
            "app.graph.neo4j_client.GraphDatabase.driver", lambda *a, **k: fake_driver
        )

        settings = Settings(neo4j_password="super-secret-password")  # type: ignore[call-arg]
        client = Neo4jClient(settings)

        with pytest.raises(Neo4jConnectionError) as exc_info:
            client.execute_write("MERGE (n:X {id: $id})", {"id": "1"})

        assert "super-secret-password" not in str(exc_info.value)

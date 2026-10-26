"""Neo4j driver lifecycle: initialization, connectivity, sessions,
transaction helpers, graceful shutdown, and fail-fast behavior.

This is the ONLY module in the codebase that imports the ``neo4j`` driver
package (AGENTS.md rule 8 analog — see graph/__init__.py: "Keep Neo4j
driver code separate from graph business logic"). graph_builder.py and
repository_graph_service.py only ever call Neo4jClient's methods with
already-parameterized Cypher from graph/queries.py — they never touch the
driver directly.

Fail-fast design (see the integration-reliability task's "Neo4j
fail-fast behavior" — the observed 30-55s wait when Neo4j is unavailable
came from the driver's own transaction-retry loop, whose default
``max_transaction_retry_time`` is ~30s):

1. ``max_transaction_retry_time`` is set to ``settings.neo4j_operation_timeout_seconds``
   (default 3s) — one call now fails in a few seconds instead of ~30s.
2. A ``CircuitBreaker`` (see app.core.dependencies.circuit_breaker) wraps
   every driver call. After ``neo4j_circuit_failure_threshold`` consecutive
   connectivity failures, the circuit opens: further calls raise
   ``Neo4jConnectionError`` immediately with **no I/O at all** until
   ``neo4j_circuit_cooldown_seconds`` has elapsed, at which point one probe
   call is allowed through (HALF_OPEN) to test recovery.

Only connectivity failures (``ServiceUnavailable``/``AuthError`` ->
``Neo4jConnectionError``) trip the breaker — a legitimate query bug
(``Neo4jQueryError``) does not, so one bad Cypher statement can't block
every other valid query.
"""

import contextlib
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

from neo4j import Driver, GraphDatabase, ManagedTransaction, Record
from neo4j.exceptions import AuthError, ConfigurationError, Neo4jError, ServiceUnavailable

from app.core.config import Settings, get_settings
from app.core.dependencies.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.graph.exceptions import Neo4jConnectionError, Neo4jQueryError

logger = logging.getLogger(__name__)

CypherParams = dict[str, object]
T = TypeVar("T")


def _is_connectivity_failure(exc: BaseException) -> bool:
    return isinstance(exc, Neo4jConnectionError)


class Neo4jClient:
    """Thin wrapper around a neo4j ``Driver``.

    Credentials are read once from Settings at construction time and never
    logged or included in any exception message raised from here (see
    SECURITY.md "Do not expose Neo4j credentials").
    """

    def __init__(
        self, settings: Settings, *, circuit_breaker: CircuitBreaker | None = None
    ) -> None:
        self._database = settings.neo4j_database
        try:
            self._driver: Driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
                connection_timeout=settings.neo4j_connection_timeout_seconds,
                max_connection_pool_size=settings.neo4j_max_connection_pool_size,
                max_transaction_retry_time=settings.neo4j_operation_timeout_seconds,
            )
        except ConfigurationError as exc:
            raise Neo4jConnectionError("Neo4j driver configuration is invalid.") from exc

        self._circuit = circuit_breaker or CircuitBreaker(
            failure_threshold=settings.neo4j_circuit_failure_threshold,
            cooldown_seconds=settings.neo4j_circuit_cooldown_seconds,
            failure_predicate=_is_connectivity_failure,
        )

    @property
    def circuit_state(self) -> CircuitState:
        """A cheap, no-I/O snapshot — used by the readiness endpoint so it
        never has to attempt a real connection while the circuit is open
        (see app.core.dependencies.status_service)."""
        return self._circuit.state

    def verify_connectivity(self) -> bool:
        """Fail-fast liveness check — never raises, used by /health/ready.
        Goes through the same circuit breaker as every other operation, so
        it can't itself become a slow call while Neo4j is down."""

        def attempt() -> None:
            try:
                self._driver.verify_connectivity()
            except (ServiceUnavailable, AuthError, Neo4jError, OSError) as exc:
                raise Neo4jConnectionError(
                    "Neo4j is unreachable or authentication failed."
                ) from exc

        try:
            self._call_through_circuit(attempt)
            return True
        except (Neo4jConnectionError, CircuitOpenError):
            return False

    def health_status(self) -> str:
        return "ok" if self.verify_connectivity() else "unavailable"

    def close(self) -> None:
        self._driver.close()

    def execute_read(self, query: str, parameters: CypherParams | None = None) -> list[Record]:
        """Run a single parameterized read query in its own transaction."""

        def work(tx: ManagedTransaction) -> list[Record]:
            return list(tx.run(query, parameters or {}))

        return self.run_read_transaction(work)

    def execute_write(self, query: str, parameters: CypherParams | None = None) -> list[Record]:
        """Run a single parameterized write query in its own transaction."""

        def work(tx: ManagedTransaction) -> list[Record]:
            return list(tx.run(query, parameters or {}))

        return self.run_write_transaction(work)

    def run_read_transaction(self, work: Callable[[ManagedTransaction], T]) -> T:
        return self._run(work, write=False)

    def run_write_transaction(self, work: Callable[[ManagedTransaction], T]) -> T:
        """Run `work` inside a single write transaction (see graph_builder.py:
        one file's whole graph is upserted atomically through this)."""
        return self._run(work, write=True)

    def _call_through_circuit(self, fn: Callable[[], T]) -> T:
        try:
            return self._circuit.call(fn)
        except CircuitOpenError as exc:
            raise Neo4jConnectionError(
                "Neo4j circuit breaker is open (repeated recent connectivity failures); "
                "failing fast without attempting a connection."
            ) from exc

    def _run(self, work: Callable[[ManagedTransaction], T], *, write: bool) -> T:
        def attempt() -> T:
            try:
                with self._driver.session(database=self._database) as session:
                    if write:
                        return session.execute_write(work)
                    return session.execute_read(work)
            except (ServiceUnavailable, AuthError) as exc:
                raise Neo4jConnectionError(
                    "Neo4j is unreachable or authentication failed."
                ) from exc
            except Neo4jError as exc:
                logger.exception("Neo4j query failed")
                raise Neo4jQueryError(f"Neo4j query failed: {exc.__class__.__name__}") from exc

        return self._call_through_circuit(attempt)


@lru_cache
def get_neo4j_client() -> Neo4jClient:
    """Cached client accessor, suitable for use as a FastAPI dependency."""
    return Neo4jClient(get_settings())


def reset_neo4j_client() -> None:
    """Test-only: close and clear the cached client.

    Call after changing Neo4j-related settings so the next
    ``get_neo4j_client()`` builds a fresh driver against them.
    """
    with contextlib.suppress(Neo4jConnectionError):
        get_neo4j_client().close()
    get_neo4j_client.cache_clear()

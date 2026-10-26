"""Demonstrates the Prompt-8-era problem (a Neo4j outage caused every
graph-dependent request to wait ~30-55s) is fixed — see the integration-
reliability task's "Neo4j outage performance test".

Uses a real ``Neo4jClient`` pointed at a deliberately unreachable address
(not the environment's configured NEO4J_URI, so this test is meaningful
and deterministic whether or not a real Neo4j happens to be running
during this test session) — this is a real driver, a real TCP connection
attempt, and a real (fast) failure; nothing here is mocked except the
target address itself. Timing assertions are deliberately loose (a
generous upper bound, not a brittle exact-millisecond check) — see "Do
NOT make an excessively brittle exact-millisecond assertion."
"""

import contextlib
import time

from app.core.config import Settings
from app.graph.exceptions import Neo4jConnectionError
from app.graph.neo4j_client import Neo4jClient

# Port 1 is a reserved, essentially-never-listening port — connecting to
# it fails fast at the TCP level regardless of this machine's actual
# network environment, unlike a "real" but currently-down Neo4j host
# (which can sometimes hang on DNS or routing before refusing).
_UNREACHABLE_URI = "bolt://127.0.0.1:1"

# The old (pre-fix) behavior waited ~30-55s per call. A fixed client
# should complete well under half of that, even accounting for this
# sandbox's own overhead.
_OLD_BEHAVIOR_FLOOR_SECONDS = 25.0


def _settings(**overrides: object) -> Settings:
    base = dict(
        neo4j_uri=_UNREACHABLE_URI,
        neo4j_connection_timeout_seconds=2,
        neo4j_operation_timeout_seconds=2,
        neo4j_circuit_failure_threshold=2,
        neo4j_circuit_cooldown_seconds=30,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestSingleCallFailsFast:
    def test_a_single_graph_call_fails_well_under_the_old_30_55s_wait(self) -> None:
        client = Neo4jClient(_settings())
        started = time.monotonic()
        with contextlib.suppress(Neo4jConnectionError):
            client.execute_read("RETURN 1", {})
        elapsed = time.monotonic() - started
        client.close()

        assert elapsed < _OLD_BEHAVIOR_FLOOR_SECONDS, (
            f"a single call took {elapsed:.1f}s — the fail-fast fix should keep this well "
            f"under the old ~30-55s behavior"
        )


class TestCircuitOpensAndFailsInstantly:
    def test_repeated_calls_become_near_instant_once_the_circuit_opens(self) -> None:
        client = Neo4jClient(_settings())

        # Two failures reach the configured threshold and open the circuit.
        for _ in range(2):
            with contextlib.suppress(Neo4jConnectionError):
                client.execute_read("RETURN 1", {})

        started = time.monotonic()
        with contextlib.suppress(Neo4jConnectionError):
            client.execute_read("RETURN 1", {})
        elapsed = time.monotonic() - started
        client.close()

        # No I/O is attempted at all once the circuit is open — this
        # should be orders of magnitude faster than a single real attempt.
        assert elapsed < 1.0, f"expected a near-instant fast rejection, took {elapsed:.2f}s"


class TestVerifyConnectivityAlsoFailsFast:
    def test_verify_connectivity_never_raises_and_is_bounded(self) -> None:
        client = Neo4jClient(_settings())
        started = time.monotonic()
        result = client.verify_connectivity()
        elapsed = time.monotonic() - started
        client.close()

        assert result is False
        assert elapsed < _OLD_BEHAVIOR_FLOOR_SECONDS

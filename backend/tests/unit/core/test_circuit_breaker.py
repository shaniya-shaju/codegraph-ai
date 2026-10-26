"""Unit tests for app.core.dependencies.circuit_breaker — a fake,
manually-advanced clock is injected throughout so these tests never
actually sleep/wait in real time."""

import pytest

from app.core.dependencies.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _boom() -> None:
    raise RuntimeError("boom")


def _ok() -> str:
    return "ok"


class TestInitialState:
    def test_starts_closed(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        assert breaker.state is CircuitState.CLOSED

    def test_closed_calls_pass_through(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        assert breaker.call(_ok) == "ok"
        assert breaker.state is CircuitState.CLOSED


class TestFailureAccumulation:
    def test_opens_after_threshold_failures(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                breaker.call(_boom)
        assert breaker.state is CircuitState.OPEN

    def test_stays_closed_below_threshold(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                breaker.call(_boom)
        assert breaker.state is CircuitState.CLOSED

    def test_a_success_in_between_resets_the_failure_count(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)
        breaker.call(_ok)  # resets the count
        with pytest.raises(RuntimeError):
            breaker.call(_boom)
        assert breaker.state is CircuitState.CLOSED


class TestFastRejectionWhenOpen:
    def test_open_circuit_rejects_without_calling_the_function(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)
        assert breaker.state is CircuitState.OPEN

        calls = []

        def tracked() -> None:
            calls.append(1)
            raise RuntimeError("should never run")

        with pytest.raises(CircuitOpenError):
            breaker.call(tracked)
        assert calls == []  # the wrapped function was never invoked


class TestCooldownAndHalfOpen:
    def test_stays_open_before_cooldown_elapses(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)

        clock.advance(29)
        with pytest.raises(CircuitOpenError):
            breaker.call(_ok)

    def test_allows_a_probe_after_cooldown_elapses(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)

        clock.advance(31)
        result = breaker.call(_ok)  # the probe call
        assert result == "ok"

    def test_successful_probe_closes_the_circuit(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)

        clock.advance(31)
        breaker.call(_ok)
        assert breaker.state is CircuitState.CLOSED

        # A subsequent call goes through normally (not fast-rejected).
        assert breaker.call(_ok) == "ok"

    def test_failed_probe_reopens_the_circuit_and_restarts_cooldown(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)

        clock.advance(31)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)  # failed probe
        assert breaker.state is CircuitState.OPEN

        # Cooldown restarted — still rejected 10s after the *second* failure.
        clock.advance(10)
        with pytest.raises(CircuitOpenError):
            breaker.call(_ok)

        # But open again after another full cooldown from the probe failure.
        clock.advance(21)
        assert breaker.call(_ok) == "ok"


class TestFailurePredicate:
    def test_only_matching_exceptions_count_as_failures(self) -> None:
        breaker = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=30,
            failure_predicate=lambda exc: isinstance(exc, ValueError),
        )

        def raise_type_error() -> None:
            raise TypeError("not counted")

        for _ in range(5):
            with pytest.raises(TypeError):
                breaker.call(raise_type_error)
        assert breaker.state is CircuitState.CLOSED

        def raise_value_error() -> None:
            raise ValueError("counted")

        with pytest.raises(ValueError):
            breaker.call(raise_value_error)
        assert breaker.state is CircuitState.OPEN


class TestReset:
    def test_reset_forces_closed(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30)
        with pytest.raises(RuntimeError):
            breaker.call(_boom)
        assert breaker.state is CircuitState.OPEN

        breaker.reset()
        assert breaker.state is CircuitState.CLOSED
        assert breaker.call(_ok) == "ok"


class TestConcurrencySafety:
    def test_concurrent_failures_do_not_corrupt_state(self) -> None:
        """100 threads hammering a breaker with failure_threshold=50: once
        it trips mid-race, later threads should be fast-rejected
        (CircuitOpenError) rather than crash with anything unexpected —
        this asserts no *corruption* (no unexpected exception type, no
        state left inconsistent), not a specific interleaving."""
        import threading

        breaker = CircuitBreaker(failure_threshold=50, cooldown_seconds=30)
        unexpected = []

        def worker() -> None:
            try:
                breaker.call(_boom)
            except (RuntimeError, CircuitOpenError):
                pass
            except Exception as exc:  # noqa: BLE001
                unexpected.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert unexpected == []
        assert breaker.state is CircuitState.OPEN  # 100 failures >> threshold of 50


class TestConstructorValidation:
    def test_rejects_non_positive_failure_threshold(self) -> None:
        with pytest.raises(ValueError):
            CircuitBreaker(failure_threshold=0, cooldown_seconds=30)

    def test_rejects_negative_cooldown(self) -> None:
        with pytest.raises(ValueError):
            CircuitBreaker(failure_threshold=1, cooldown_seconds=-1)

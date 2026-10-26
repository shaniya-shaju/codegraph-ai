"""A small, generic, reusable circuit breaker — see the integration-
reliability task's "Neo4j fail-fast behavior": "Create a reusable
circuit-breaker abstraction if appropriate."

Not Neo4j-specific: it wraps any zero-argument callable and decides
whether a raised exception counts as a "failure" via an injectable
predicate (defaulting to "every exception counts"), so it can wrap any
flaky dependency call, not just Neo4j's.

States (see "Example states"):

    CLOSED    -> calls go through normally.
    OPEN      -> calls are rejected immediately (CircuitOpenError), no
                 wrapped call is ever attempted, until the cooldown
                 elapses.
    HALF_OPEN -> the cooldown has elapsed; the next call(s) are allowed
                 through as a probe. A success closes the circuit; a
                 counted failure reopens it (restarting the cooldown).

Thread-safe (a single ``threading.Lock`` guards state transitions) and
testable without real waiting — the clock is injectable (``clock``
parameter), so unit tests advance a fake clock instead of sleeping.
"""

import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised by ``CircuitBreaker.call()`` when the circuit is open — the
    wrapped callable was never invoked."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int,
        cooldown_seconds: float,
        failure_predicate: Callable[[BaseException], bool] = lambda _exc: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1.")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative.")
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._failure_predicate = failure_predicate
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        """A snapshot of the current state. Reading this never mutates
        state — only ``call()`` can transition OPEN -> HALF_OPEN (on the
        next actual call attempt), so this may still report OPEN even
        after the cooldown has technically elapsed until the next call."""
        with self._lock:
            return self._state

    def call(self, fn: Callable[[], T]) -> T:
        """Run ``fn()`` if the circuit allows it; raise
        ``CircuitOpenError`` without calling ``fn`` otherwise."""
        self._before_call()
        try:
            result = fn()
        except BaseException as exc:
            if self._failure_predicate(exc):
                self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def reset(self) -> None:
        """Force the circuit back to CLOSED — test/ops escape hatch."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None

    def _before_call(self) -> None:
        with self._lock:
            if self._state is CircuitState.OPEN:
                assert self._opened_at is not None
                if self._clock() - self._opened_at >= self._cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitOpenError(
                        "Circuit breaker is open; failing fast without attempting the call."
                    )

    def _on_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None

    def _on_failure(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                # The probe failed — reopen immediately and restart the cooldown.
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()
                return
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()

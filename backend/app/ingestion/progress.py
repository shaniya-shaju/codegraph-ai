"""In-memory analysis-progress events — see the integration-reliability
task's "Progress events" and "Analysis progress streaming": "If a robust
SSE implementation requires an in-memory event broadcaster, keep it
simple... Persisted state remains the source of truth... Do not
introduce Redis solely for this feature."

``RepositoryAnalysisState`` (app.persistence.models, updated via
app.ingestion.analysis_state_service) is always the durable source of
truth. This broadcaster only serves *live* subscribers connected right
now — an SSE client that reconnects after missing events just re-reads
the persisted state via GET .../analysis, which is why event delivery
here doesn't need to be lossless or persisted itself.
"""

import contextlib
import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

_SUBSCRIBER_QUEUE_MAXSIZE = 100
_SUBSCRIBER_POLL_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class AnalysisProgressEvent:
    repository_id: str
    job_id: str

    stage: str
    status: str

    progress_percentage: float

    message: str | None = None

    files_processed: int | None = None
    files_total: int | None = None

    created_at: float = field(default_factory=time.time)


class _RepositoryBroadcaster:
    """Fan-out for one repository_id's live subscribers. Never buffers
    events for a subscriber that isn't currently connected — a full queue
    just drops the oldest event for that one slow subscriber rather than
    blocking the publisher (the orchestrator thread) or growing without
    bound."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[AnalysisProgressEvent]] = set()

    def subscribe(self) -> "queue.Queue[AnalysisProgressEvent]":
        q: queue.Queue[AnalysisProgressEvent] = queue.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "queue.Queue[AnalysisProgressEvent]") -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: AnalysisProgressEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                # A slow/stalled subscriber: drop its oldest event to make
                # room rather than blocking the publisher or growing
                # unbounded (see this module's docstring).
                with contextlib.suppress(queue.Empty):
                    q.get_nowait()
                with contextlib.suppress(queue.Full):
                    q.put_nowait(event)


class ProgressBroadcaster:
    """One ``_RepositoryBroadcaster`` per repository_id, created lazily.
    A single process-wide instance (``get_broadcaster()``) is shared by
    the orchestrator (publisher) and the SSE endpoint (subscriber)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_repository: dict[str, _RepositoryBroadcaster] = {}

    def _get(self, repository_id: str) -> _RepositoryBroadcaster:
        with self._lock:
            broadcaster = self._by_repository.get(repository_id)
            if broadcaster is None:
                broadcaster = _RepositoryBroadcaster()
                self._by_repository[repository_id] = broadcaster
            return broadcaster

    def publish(self, event: AnalysisProgressEvent) -> None:
        self._get(event.repository_id).publish(event)

    @contextmanager
    def subscribe(self, repository_id: str) -> Iterator["queue.Queue[AnalysisProgressEvent]"]:
        broadcaster = self._get(repository_id)
        q = broadcaster.subscribe()
        try:
            yield q
        finally:
            broadcaster.unsubscribe(q)

    def poll(
        self,
        q: "queue.Queue[AnalysisProgressEvent]",
        *,
        timeout: float = _SUBSCRIBER_POLL_TIMEOUT_SECONDS,
    ) -> AnalysisProgressEvent | None:
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None


_broadcaster = ProgressBroadcaster()


def get_broadcaster() -> ProgressBroadcaster:
    return _broadcaster

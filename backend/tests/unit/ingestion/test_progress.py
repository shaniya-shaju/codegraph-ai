"""Unit tests for app.ingestion.progress — the in-memory, best-effort
live-subscriber progress broadcaster."""

from app.ingestion.progress import AnalysisProgressEvent, ProgressBroadcaster


def _event(repository_id: str = "repo-1", stage: str = "PARSE", progress: float = 30.0):
    return AnalysisProgressEvent(
        repository_id=repository_id,
        job_id="job-1",
        stage=stage,
        status="RUNNING",
        progress_percentage=progress,
    )


class TestSubscribeAndPublish:
    def test_subscriber_receives_a_published_event(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q:
            broadcaster.publish(_event())
            received = broadcaster.poll(q, timeout=1.0)
        assert received is not None
        assert received.stage == "PARSE"

    def test_events_for_a_different_repository_are_not_received(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q:
            broadcaster.publish(_event(repository_id="repo-2"))
            received = broadcaster.poll(q, timeout=0.2)
        assert received is None

    def test_poll_times_out_with_no_events(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q:
            received = broadcaster.poll(q, timeout=0.2)
        assert received is None

    def test_multiple_subscribers_each_receive_the_event(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q1, broadcaster.subscribe("repo-1") as q2:
            broadcaster.publish(_event())
            assert broadcaster.poll(q1, timeout=1.0) is not None
            assert broadcaster.poll(q2, timeout=1.0) is not None

    def test_unsubscribed_queue_is_no_longer_delivered_to(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q:
            pass  # unsubscribed on context exit
        broadcaster.publish(_event())
        assert broadcaster.poll(q, timeout=0.2) is None

    def test_publish_with_no_subscribers_does_not_raise(self) -> None:
        broadcaster = ProgressBroadcaster()
        broadcaster.publish(_event())  # no subscribers at all — must be a no-op


class TestOrderedStages:
    def test_events_are_received_in_publish_order(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q:
            broadcaster.publish(_event(stage="SCAN", progress=10.0))
            broadcaster.publish(_event(stage="PARSE", progress=30.0))
            broadcaster.publish(_event(stage="BUILD_GRAPH", progress=60.0))

            stages = [broadcaster.poll(q, timeout=1.0).stage for _ in range(3)]  # type: ignore[union-attr]
        assert stages == ["SCAN", "PARSE", "BUILD_GRAPH"]

    def test_progress_percentage_is_monotonic_across_received_events(self) -> None:
        broadcaster = ProgressBroadcaster()
        with broadcaster.subscribe("repo-1") as q:
            for progress in (10.0, 30.0, 60.0, 100.0):
                broadcaster.publish(_event(progress=progress))
            values = []
            for _ in range(4):
                event = broadcaster.poll(q, timeout=1.0)
                assert event is not None
                values.append(event.progress_percentage)
        assert values == sorted(values)

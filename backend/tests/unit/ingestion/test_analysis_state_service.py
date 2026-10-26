"""Unit tests for app.ingestion.analysis_state_service — the only place
overall_status is derived from subsystem statuses (see the module's own
docstring)."""

from app.core.database import get_session_factory
from app.domain.repositories.enums import AnalysisStage, OverallStatus, SubsystemStatus
from app.ingestion import analysis_state_service as svc


def _session():
    return get_session_factory()()


class TestDeriveOverallStatus:
    def test_fully_healthy(self) -> None:
        assert (
            svc.derive_overall_status(
                parser=SubsystemStatus.READY,
                graph=SubsystemStatus.READY,
                vector=SubsystemStatus.READY,
            )
            is OverallStatus.READY
        )

    def test_neo4j_failure_is_partial(self) -> None:
        assert (
            svc.derive_overall_status(
                parser=SubsystemStatus.READY,
                graph=SubsystemStatus.FAILED,
                vector=SubsystemStatus.READY,
            )
            is OverallStatus.PARTIAL
        )

    def test_embedding_failure_is_partial(self) -> None:
        assert (
            svc.derive_overall_status(
                parser=SubsystemStatus.READY,
                graph=SubsystemStatus.READY,
                vector=SubsystemStatus.FAILED,
            )
            is OverallStatus.PARTIAL
        )

    def test_parser_catastrophic_failure(self) -> None:
        assert (
            svc.derive_overall_status(
                parser=SubsystemStatus.FAILED,
                graph=SubsystemStatus.NOT_STARTED,
                vector=SubsystemStatus.NOT_STARTED,
            )
            is OverallStatus.FAILED
        )

    def test_still_running(self) -> None:
        assert (
            svc.derive_overall_status(
                parser=SubsystemStatus.READY,
                graph=SubsystemStatus.RUNNING,
                vector=SubsystemStatus.NOT_STARTED,
            )
            is OverallStatus.RUNNING
        )

    def test_stale(self) -> None:
        assert (
            svc.derive_overall_status(
                parser=SubsystemStatus.READY,
                graph=SubsystemStatus.STALE,
                vector=SubsystemStatus.READY,
            )
            is OverallStatus.STALE
        )


class TestNormalProgression:
    def test_start_run_then_finalize_produces_ready(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1", files_total=5)
        svc.mark_parser_result(
            session,
            "repo-1",
            status=SubsystemStatus.READY,
            files_total=5,
            files_processed=5,
            files_failed=0,
        )
        svc.mark_graph_result(
            session, "repo-1", status=SubsystemStatus.READY, node_count=10, revision="rev1"
        )
        svc.mark_vector_result(
            session, "repo-1", status=SubsystemStatus.READY, chunk_count=20, revision="rev1"
        )
        state = svc.finalize_run(
            session, "repo-1", repository_revision="rev1", total_duration_ms=500
        )

        assert state.overall_status == OverallStatus.READY.value
        assert state.current_stage == AnalysisStage.DONE.value
        assert state.progress_percentage == 100.0
        assert state.total_duration_ms == 500
        session.close()


class TestPartialFailures:
    def test_partial_graph_failure(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.mark_parser_result(
            session,
            "repo-1",
            status=SubsystemStatus.READY,
            files_total=1,
            files_processed=1,
            files_failed=0,
        )
        svc.mark_graph_result(
            session, "repo-1", status=SubsystemStatus.FAILED, error="Neo4j unreachable"
        )
        svc.mark_vector_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        state = svc.finalize_run(session, "repo-1", repository_revision="rev1")

        assert state.overall_status == OverallStatus.PARTIAL.value
        assert "Neo4j unreachable" in svc.errors_of(state)
        session.close()

    def test_partial_vector_failure(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.mark_parser_result(
            session,
            "repo-1",
            status=SubsystemStatus.READY,
            files_total=1,
            files_processed=1,
            files_failed=0,
        )
        svc.mark_graph_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.mark_vector_result(
            session, "repo-1", status=SubsystemStatus.FAILED, error="embedding model failed"
        )
        state = svc.finalize_run(session, "repo-1", repository_revision="rev1")

        assert state.overall_status == OverallStatus.PARTIAL.value
        session.close()

    def test_parser_failure_is_terminal(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        state = svc.mark_run_failed(session, "repo-1", error="catastrophic parse error")

        assert state.overall_status == OverallStatus.FAILED.value
        assert state.graph_status == SubsystemStatus.NOT_STARTED.value
        assert state.vector_status == SubsystemStatus.NOT_STARTED.value
        session.close()


class TestStaleness:
    def test_content_change_marks_graph_and_vector_stale(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.mark_parser_result(
            session,
            "repo-1",
            status=SubsystemStatus.READY,
            files_total=1,
            files_processed=1,
            files_failed=0,
        )
        svc.mark_graph_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.mark_vector_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.finalize_run(session, "repo-1", repository_revision="rev1")

        state = svc.check_and_mark_stale(session, "repo-1", current_repository_revision="rev2")

        assert state is not None
        assert state.graph_status == SubsystemStatus.STALE.value
        assert state.vector_status == SubsystemStatus.STALE.value
        assert state.overall_status == OverallStatus.STALE.value
        session.close()

    def test_unchanged_revision_is_a_no_op(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.mark_graph_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.mark_vector_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.finalize_run(session, "repo-1", repository_revision="rev1")

        state = svc.check_and_mark_stale(session, "repo-1", current_repository_revision="rev1")

        assert state is not None
        assert state.graph_status == SubsystemStatus.READY.value
        session.close()


class TestForceReanalysis:
    def test_is_current_true_only_when_ready_and_matching_revision(
        self, isolated_database: None
    ) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.mark_graph_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.mark_vector_result(session, "repo-1", status=SubsystemStatus.READY, revision="rev1")
        svc.mark_parser_result(
            session,
            "repo-1",
            status=SubsystemStatus.READY,
            files_total=1,
            files_processed=1,
            files_failed=0,
        )
        state = svc.finalize_run(session, "repo-1", repository_revision="rev1")

        assert svc.is_current(state, "rev1") is True
        assert svc.is_current(state, "rev2") is False
        assert svc.is_current(None, "rev1") is False
        session.close()


class TestProgressMonotonicity:
    def test_progress_never_decreases_within_a_run(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.update_stage(session, "repo-1", stage=AnalysisStage.BUILD_GRAPH)  # -> 70
        state = svc.update_stage(
            session, "repo-1", stage=AnalysisStage.SCAN
        )  # would be 20, clamped up
        assert state.progress_percentage >= 70.0
        session.close()


class TestDeleteState:
    def test_delete_removes_the_row(self, isolated_database: None) -> None:
        session = _session()
        svc.start_run(session, "repo-1", job_id="job-1")
        svc.delete_state(session, "repo-1")
        assert svc.get_state(session, "repo-1") is None
        session.close()

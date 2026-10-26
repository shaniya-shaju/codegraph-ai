"""Enumerations for repository-analysis state tracking — see the
integration-reliability task's "Repository analysis state".
"""

from enum import StrEnum


class SubsystemStatus(StrEnum):
    """Per-subsystem (parser/graph/vector) status — see "Each subsystem
    should have its own status"."""

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    STALE = "STALE"


class OverallStatus(StrEnum):
    """The repository's overall analysis status — derived from its
    subsystem statuses, never set independently (see
    app.ingestion.analysis_state_service.derive_overall_status): "Do not
    mark a repository fully READY if required graph or vector analysis
    failed."."""

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    STALE = "STALE"


class AnalysisStage(StrEnum):
    """See "Analysis orchestration": "The orchestration service should own
    stage transitions." Order matters — it's the pipeline order."""

    IMPORT = "IMPORT"
    SCAN = "SCAN"
    PARSE = "PARSE"
    BUILD_GRAPH = "BUILD_GRAPH"
    BUILD_VECTOR_INDEX = "BUILD_VECTOR_INDEX"
    FINALIZE = "FINALIZE"
    DONE = "DONE"

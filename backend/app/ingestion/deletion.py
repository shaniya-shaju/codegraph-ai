"""Ordered, best-effort cross-store repository deletion — see the
integration-reliability task's "Repository deletion": "Since cross-
database distributed transactions are unavailable, implement: ordered
cleanup, error collection, retryable partial-cleanup status. Do not mark
deletion successful if major cleanup fails silently."

Cleanup order (each step is independent — one failing never skips the
rest): Neo4j graph -> Chroma collection + indexing manifest -> conversation
messages -> analysis state -> workspace files -> the RepositoryRecord row
itself (deleted last, so a repository that partially failed to clean up
is still visible/retryable via its own id rather than disappearing while
orphaned data remains in other stores).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.domain.repositories.store import get_repository
from app.graph.exceptions import GraphError
from app.graph.graph_builder import delete_repository_graph
from app.graph.neo4j_client import Neo4jClient
from app.indexing.indexing_service import delete_repository_index
from app.indexing.vector_store import VectorStore
from app.ingestion import analysis_state_service as state_service
from app.ingestion.analysis import repository_workspace
from app.ingestion.workspace import cleanup_workspace
from app.rag.conversation_context import delete_conversation_messages_for_repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeletionResult:
    repository_id: str
    cleaned_stores: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def fully_cleaned(self) -> bool:
        return not self.errors


def delete_repository_everywhere(
    session: Session, *, repository_id: str, neo4j_client: Neo4jClient, vector_store: VectorStore
) -> DeletionResult:
    cleaned: list[str] = []
    errors: list[str] = []

    def _step(name: str, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - collect and continue; never abort the run
            logger.warning("Cleanup step %r failed for repository %s: %s", name, repository_id, exc)
            errors.append(f"{name}: {exc}")
        else:
            cleaned.append(name)

    _step("neo4j_graph", lambda: _delete_graph(neo4j_client, repository_id))
    _step(
        "chroma_and_manifest",
        lambda: delete_repository_index(session, vector_store, repository_id=repository_id),
    )
    _step(
        "conversation_messages",
        lambda: delete_conversation_messages_for_repository(session, repository_id),
    )
    _step("analysis_state", lambda: state_service.delete_state(session, repository_id))
    _step("workspace_files", lambda: cleanup_workspace(repository_workspace(repository_id)))

    # The RepositoryRecord row is only removed once every external-store
    # step has been *attempted* — see this module's docstring on ordering.
    def _delete_record() -> None:
        record = get_repository(session, repository_id)
        if record is not None:
            session.delete(record)
            session.commit()

    _step("repository_record", _delete_record)

    return DeletionResult(repository_id=repository_id, cleaned_stores=cleaned, errors=errors)


def _delete_graph(neo4j_client: Neo4jClient, repository_id: str) -> None:
    try:
        delete_repository_graph(neo4j_client, repository_id)
    except GraphError as exc:
        raise RuntimeError(f"graph deletion failed: {exc}") from exc

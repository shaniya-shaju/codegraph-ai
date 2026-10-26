"""Hybrid graph + vector retrieval endpoint.

Extends API_SPEC.md's repository contract — see the hybrid-retrieval
task's "API endpoint". Returns a structured retrieval result only; no
endpoint here generates a final natural-language answer (that is a later
stage — see app.rag.hybrid_retriever's module docstring).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.domain.rag.enums import RetrievalMode
from app.domain.rag.models import HybridRetrievalResult
from app.domain.repositories.store import get_repository
from app.graph.neo4j_client import Neo4jClient, get_neo4j_client
from app.indexing.chroma_store import get_vector_store
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.sentence_transformer_provider import get_embedding_provider
from app.indexing.vector_store import VectorStore
from app.rag.exceptions import RagError
from app.rag.hybrid_retriever import retrieve
from app.rag.llm_provider import StructuredLLMProvider, get_structured_llm_provider

router = APIRouter(tags=["retrieval"])


def _require_repository(repository_id: str, db: Session = Depends(get_db)) -> str:
    if get_repository(db, repository_id) is None:
        raise NotFoundError(f"No repository with id {repository_id} exists.")
    return repository_id


def _graph_client() -> Neo4jClient:
    return get_neo4j_client()


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: RetrievalMode = RetrievalMode.HYBRID
    top_k: int | None = Field(default=None, ge=1)


@router.post("/repositories/{repository_id}/retrieve", response_model=HybridRetrievalResult)
async def retrieve_evidence(
    payload: RetrieveRequest,
    *,
    repository_id: str = Depends(_require_repository),
    settings: Settings = Depends(get_settings),
    client: Neo4jClient = Depends(_graph_client),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    vector_store: VectorStore = Depends(get_vector_store),
    llm_provider: StructuredLLMProvider | None = Depends(get_structured_llm_provider),
) -> HybridRetrievalResult:
    try:
        return await retrieve(
            repository_id=repository_id,
            question=payload.question,
            mode=payload.mode,
            top_k=payload.top_k,
            settings=settings,
            neo4j_client=client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm_provider,
        )
    except RagError as exc:
        raise ValidationError(str(exc)) from exc

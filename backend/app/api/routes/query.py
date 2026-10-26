"""Grounded question-answering endpoints.

Extends API_SPEC.md's repository contract — see the answer-generation
task's "API". No endpoint here generates or accepts Cypher, and every
citation in a response is validated against real retrieval evidence
before it's returned (see app.rag.citation_validator).
"""

import dataclasses
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.domain.rag.enums import RetrievalMode
from app.domain.repositories.store import get_repository
from app.graph.neo4j_client import Neo4jClient, get_neo4j_client
from app.indexing.chroma_store import get_vector_store
from app.indexing.embedding_provider import EmbeddingProvider
from app.indexing.sentence_transformer_provider import get_embedding_provider
from app.indexing.vector_store import VectorStore
from app.rag import answer_service
from app.rag.answer_models import (
    AnswerConfidence,
    CodeAnswer,
    CodeCitation,
    ResolvedSymbolReference,
)
from app.rag.exceptions import ConversationRepositoryMismatchError
from app.rag.llm_provider import (
    AnswerLLMProvider,
    StructuredLLMProvider,
    get_answer_llm_provider,
    get_structured_llm_provider,
)

router = APIRouter(tags=["query"])


def _require_repository(repository_id: str, db: Session = Depends(get_db)) -> str:
    if get_repository(db, repository_id) is None:
        raise NotFoundError(f"No repository with id {repository_id} exists.")
    return repository_id


def _graph_client() -> Neo4jClient:
    return get_neo4j_client()


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
    # No conversation_id -> a fully stateless, one-off query: nothing is
    # persisted (see "Keep the system usable without conversation
    # context."). To start a trackable conversation, the caller
    # generates its own id and passes it from the first message onward.
    conversation_id: str | None = None


@dataclass(frozen=True)
class QueryResponse:
    answer: str
    citations: list[CodeCitation]
    confidence_level: AnswerConfidence
    confidence_reason: str
    retrieval_mode: str
    primary_intent: str
    resolved_symbols: list[ResolvedSymbolReference]
    limitations: list[str]
    abstained: bool
    # Echoed back exactly as given (or null) — see QueryRequest.conversation_id.
    conversation_id: str | None

    @classmethod
    def from_answer(cls, answer: CodeAnswer, *, conversation_id: str | None) -> "QueryResponse":
        return cls(
            answer=answer.answer,
            citations=answer.citations,
            confidence_level=answer.confidence_level,
            confidence_reason=answer.confidence_reason,
            retrieval_mode=answer.retrieval_mode,
            primary_intent=answer.primary_intent,
            resolved_symbols=answer.resolved_symbols,
            limitations=answer.limitations,
            abstained=answer.abstained,
            conversation_id=conversation_id,
        )


def _llm_provider() -> AnswerLLMProvider:
    return get_answer_llm_provider()


def _query_analyzer_llm_provider() -> StructuredLLMProvider | None:
    return get_structured_llm_provider()


@router.post("/repositories/{repository_id}/query", response_model=QueryResponse)
async def query_repository(
    payload: QueryRequest,
    *,
    repository_id: str = Depends(_require_repository),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    client: Neo4jClient = Depends(_graph_client),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    vector_store: VectorStore = Depends(get_vector_store),
    llm_provider: AnswerLLMProvider = Depends(_llm_provider),
    query_analyzer_llm_provider: StructuredLLMProvider | None = Depends(
        _query_analyzer_llm_provider
    ),
) -> QueryResponse:
    try:
        answer = await answer_service.answer_question(
            db,
            repository_id=repository_id,
            question=payload.question,
            retrieval_mode=payload.retrieval_mode,
            conversation_id=payload.conversation_id,
            settings=settings,
            neo4j_client=client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm_provider,
            query_analyzer_llm_provider=query_analyzer_llm_provider,
        )
    except ConversationRepositoryMismatchError as exc:
        raise ValidationError(str(exc)) from exc

    return QueryResponse.from_answer(answer, conversation_id=payload.conversation_id)


@router.post("/repositories/{repository_id}/query/stream")
async def query_repository_stream(
    payload: QueryRequest,
    *,
    repository_id: str = Depends(_require_repository),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    client: Neo4jClient = Depends(_graph_client),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    vector_store: VectorStore = Depends(get_vector_store),
    llm_provider: AnswerLLMProvider = Depends(_llm_provider),
    query_analyzer_llm_provider: StructuredLLMProvider | None = Depends(
        _query_analyzer_llm_provider
    ),
) -> StreamingResponse:
    """SSE stream of raw answer text as it's generated (``event: chunk``),
    followed by exactly one ``event: final`` carrying the fully
    validated/finalized ``QueryResponse`` — citations are only ever
    finalized after generation completes, never mid-stream (see
    app.rag.answer_service.stream_answer)."""

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event in answer_service.stream_answer(
                db,
                repository_id=repository_id,
                question=payload.question,
                retrieval_mode=payload.retrieval_mode,
                conversation_id=payload.conversation_id,
                settings=settings,
                neo4j_client=client,
                embedding_provider=embedding_provider,
                vector_store=vector_store,
                llm_provider=llm_provider,
                query_analyzer_llm_provider=query_analyzer_llm_provider,
            ):
                if event["type"] == "chunk":
                    data = json.dumps({"text": event["text"]})
                    yield f"event: chunk\ndata: {data}\n\n"
                else:
                    response = QueryResponse.from_answer(
                        cast(CodeAnswer, event["answer"]), conversation_id=payload.conversation_id
                    )
                    data = json.dumps(dataclasses.asdict(response))
                    yield f"event: final\ndata: {data}\n\n"
        except ConversationRepositoryMismatchError as exc:
            data = json.dumps({"error": str(exc)})
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")

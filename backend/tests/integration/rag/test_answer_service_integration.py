"""Grounded answer generation against the real sample repository (real
Neo4j + real embedded Chroma — see conftest.py for how to run this when
Neo4j isn't reachable). The LLM itself is still faked (see the
answer-generation task: "No external model calls in the ordinary test
suite.") — only retrieval is real here.
"""

from tests.fakes import FakeAnswerLLMProvider

from app.domain.rag.enums import RetrievalMode
from app.rag import answer_service
from app.rag.answer_generator import LLMAnswerOutput
from app.rag.answer_models import AnswerConfidence


class TestGroundedAnswerAgainstARealRepository:
    async def test_explain_login_produces_a_cited_non_abstained_answer(
        self,
        sample_repository,
        neo4j_client,
        vector_store,
        embedding_provider,
        indexing_settings,
        isolated_database,
    ) -> None:
        from app.core.database import get_session_factory

        llm = FakeAnswerLLMProvider(
            structured_result=LLMAnswerOutput(
                answer="login authenticates a user by email and password [E1]."
            )
        )
        session = get_session_factory()()

        answer = await answer_service.answer_question(
            session,
            repository_id=sample_repository,
            question="Explain login().",
            retrieval_mode=RetrievalMode.HYBRID,
            conversation_id=None,
            settings=indexing_settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm,
            query_analyzer_llm_provider=None,
        )

        assert answer.abstained is False
        assert answer.citations
        assert answer.citations[0].file_path == "app/auth.py"
        assert answer.confidence_level != AnswerConfidence.INSUFFICIENT_EVIDENCE
        session.close()

    async def test_unresolvable_symbol_abstains_without_calling_the_llm(
        self,
        sample_repository,
        neo4j_client,
        vector_store,
        embedding_provider,
        indexing_settings,
        isolated_database,
    ) -> None:
        from app.core.database import get_session_factory

        llm = FakeAnswerLLMProvider(
            structured_result=LLMAnswerOutput(answer="should never be used [E1].")
        )
        session = get_session_factory()()

        answer = await answer_service.answer_question(
            session,
            repository_id=sample_repository,
            question="Explain totally_nonexistent_symbol_xyz().",
            retrieval_mode=RetrievalMode.HYBRID,
            conversation_id=None,
            settings=indexing_settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm,
            query_analyzer_llm_provider=None,
        )

        assert answer.abstained is True
        assert llm.generate_structured_calls == []
        session.close()

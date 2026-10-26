"""LLM answer generation: structured + streaming paths, sentinel-line
parsing, and controlled failure handling. Uses FakeAnswerLLMProvider only
— no external model calls."""

import pytest

from app.rag.answer_generator import (
    LLMAnswerOutput,
    generate_answer,
    parse_streamed_text,
    stream_answer_text,
)
from app.rag.exceptions import LLMAnalysisError
from tests.fakes import FakeAnswerLLMProvider


class TestGenerateAnswerStructuredPath:
    async def test_returns_the_structured_result(self) -> None:
        result = LLMAnswerOutput(
            answer="login is here [E1].", sufficient_evidence=True, uncertainty_notes=[]
        )
        provider = FakeAnswerLLMProvider(structured_result=result)

        generated = await generate_answer(
            provider, question="q", evidence_block="ev", timeout_seconds=5
        )

        assert generated.raw_answer_text == "login is here [E1]."
        assert generated.sufficient_evidence is True
        assert generated.had_citation_markers is True

    async def test_uncertainty_notes_are_preserved(self) -> None:
        result = LLMAnswerOutput(
            answer="It calls X [E1].",
            sufficient_evidence=True,
            uncertainty_notes=["static analysis cannot confirm runtime dispatch"],
        )
        provider = FakeAnswerLLMProvider(structured_result=result)

        generated = await generate_answer(
            provider, question="q", evidence_block="ev", timeout_seconds=5
        )

        assert "static analysis cannot confirm runtime dispatch" in generated.uncertainty_notes

    async def test_propagates_llm_analysis_error(self) -> None:
        provider = FakeAnswerLLMProvider(structured_error=LLMAnalysisError("boom"))

        with pytest.raises(LLMAnalysisError):
            await generate_answer(provider, question="q", evidence_block="ev", timeout_seconds=5)

    async def test_stray_sentinel_lines_are_stripped_defensively(self) -> None:
        result = LLMAnswerOutput(
            answer="Answer text [E1].\nSUFFICIENT_EVIDENCE: true\nNOTE: extra note",
            sufficient_evidence=True,
        )
        provider = FakeAnswerLLMProvider(structured_result=result)

        generated = await generate_answer(
            provider, question="q", evidence_block="ev", timeout_seconds=5
        )

        assert "SUFFICIENT_EVIDENCE" not in generated.raw_answer_text
        assert "extra note" in generated.uncertainty_notes

    async def test_prompts_contain_the_question_and_evidence(self) -> None:
        result = LLMAnswerOutput(answer="ok [E1].")
        provider = FakeAnswerLLMProvider(structured_result=result)

        await generate_answer(
            provider,
            question="Where is login?",
            evidence_block="[E1] def login()",
            timeout_seconds=5,
        )

        call = provider.generate_structured_calls[0]
        assert "Where is login?" in call["user_prompt"]
        assert "[E1] def login()" in call["user_prompt"]


class TestStreamingPath:
    async def test_stream_yields_chunks_in_order(self) -> None:
        provider = FakeAnswerLLMProvider(stream_chunks=["Login ", "is here ", "[E1]."])

        chunks = [c async for c in stream_answer_text(provider, question="q", evidence_block="ev")]

        assert chunks == ["Login ", "is here ", "[E1]."]

    async def test_stream_error_propagates(self) -> None:
        provider = FakeAnswerLLMProvider(stream_error=LLMAnalysisError("stream failed"))

        with pytest.raises(LLMAnalysisError):
            async for _ in stream_answer_text(provider, question="q", evidence_block="ev"):
                pass


class TestParseStreamedText:
    def test_extracts_sentinel_and_notes(self) -> None:
        full_text = (
            "Login is here [E1].\nSUFFICIENT_EVIDENCE: false\n"
            "NOTE: weak evidence\nNOTE: second note"
        )

        generated = parse_streamed_text(full_text)

        assert generated.raw_answer_text == "Login is here [E1]."
        assert generated.sufficient_evidence is False
        assert generated.uncertainty_notes == ["weak evidence", "second note"]
        assert generated.had_citation_markers is True

    def test_missing_sentinel_defaults_to_sufficient_true(self) -> None:
        generated = parse_streamed_text("Just an answer with no sentinel [E1].")
        assert generated.sufficient_evidence is True

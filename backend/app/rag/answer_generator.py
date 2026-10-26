"""LLM answer generation — the only module that actually calls the LLM
for a grounded answer. Two paths share one parsing pipeline:

- ``generate_answer`` (non-streaming): asks for a typed
  ``LLMAnswerOutput`` via ``AnswerLLMProvider.generate_structured``.
- ``stream_answer_text`` (streaming): asks for plain text via
  ``AnswerLLMProvider.generate_text_stream``; the caller accumulates the
  full text and passes it to ``parse_streamed_text`` once streaming
  finishes — citations are only ever finalized/validated after
  generation completes either way (see citation_validator.py /
  answer_service.py), never mid-stream.

Citation markers (``[E<n>]``) are never trusted from a separately
LLM-declared list — they're always parsed out of the answer text itself
(see citation_validator.py), so both paths produce the same shape.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.rag.answer_prompts import ANSWER_SYSTEM_PROMPT, build_answer_user_prompt
from app.rag.exceptions import LLMAnalysisError
from app.rag.llm_provider import AnswerLLMProvider

_SUFFICIENT_EVIDENCE_RE = re.compile(
    r"^SUFFICIENT_EVIDENCE:\s*(true|false)\s*$", re.IGNORECASE | re.MULTILINE
)
_NOTE_RE = re.compile(r"^NOTE:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


class LLMAnswerOutput(BaseModel):
    """What the structured (non-streaming) path asks the LLM to fill —
    see the answer-generation task's system-prompt rules 6-8."""

    answer: str
    sufficient_evidence: bool = True
    uncertainty_notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class GeneratedAnswer:
    raw_answer_text: str
    sufficient_evidence: bool
    uncertainty_notes: list[str] = field(default_factory=list)
    had_citation_markers: bool = False


def _strip_sentinel_lines(text: str) -> tuple[str, list[str]]:
    """Defensively strips the streaming path's ``SUFFICIENT_EVIDENCE:``/
    ``NOTE:`` sentinel lines out of the visible answer even on the
    structured path, in case a model redundantly includes them inside
    the ``answer`` field too."""
    notes = [m.strip() for m in _NOTE_RE.findall(text) if m.strip()]
    body = _SUFFICIENT_EVIDENCE_RE.sub("", text)
    body = _NOTE_RE.sub("", body)
    return body.strip(), notes


def _has_citation_markers(text: str) -> bool:
    return re.search(r"\[E\d+\]", text) is not None


async def generate_answer(
    provider: AnswerLLMProvider,
    *,
    question: str,
    evidence_block: str,
    timeout_seconds: float,
) -> GeneratedAnswer:
    user_prompt = build_answer_user_prompt(question, evidence_block)
    try:
        result = await asyncio.wait_for(
            provider.generate_structured(
                system_prompt=ANSWER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                output_schema=LLMAnswerOutput,
            ),
            timeout=timeout_seconds,
        )
    except LLMAnalysisError:
        raise
    except TimeoutError as exc:
        raise LLMAnalysisError("Answer generation timed out.") from exc
    except Exception as exc:  # pragma: no cover - defensive; provider already wraps most errors
        raise LLMAnalysisError(f"Answer generation failed: {exc}") from exc

    cleaned_answer, extra_notes = _strip_sentinel_lines(result.answer)
    notes = list(result.uncertainty_notes)
    notes.extend(n for n in extra_notes if n not in notes)
    return GeneratedAnswer(
        raw_answer_text=cleaned_answer,
        sufficient_evidence=result.sufficient_evidence,
        uncertainty_notes=notes,
        had_citation_markers=_has_citation_markers(result.answer),
    )


def stream_answer_text(
    provider: AnswerLLMProvider, *, question: str, evidence_block: str
) -> AsyncIterator[str]:
    """Yields raw text chunks as they arrive. The caller is responsible
    for accumulating them and calling ``parse_streamed_text`` on the full
    text once the stream ends — see this module's docstring."""
    user_prompt = build_answer_user_prompt(question, evidence_block)
    return provider.generate_text_stream(
        system_prompt=ANSWER_SYSTEM_PROMPT, user_prompt=user_prompt
    )


def parse_streamed_text(full_text: str) -> GeneratedAnswer:
    """Parses the accumulated streamed text once generation has
    finished. A missing ``SUFFICIENT_EVIDENCE:`` sentinel line defaults
    to ``True`` — the relevance/citation checks (see
    grounding_validator.py) are the primary safety net either way, so a
    model that simply forgets the sentinel format doesn't need to force
    an otherwise-well-grounded answer into abstention."""
    cleaned_answer, notes = _strip_sentinel_lines(full_text)
    match = _SUFFICIENT_EVIDENCE_RE.search(full_text)
    sufficient_evidence = match.group(1).lower() == "true" if match else True
    return GeneratedAnswer(
        raw_answer_text=cleaned_answer,
        sufficient_evidence=sufficient_evidence,
        uncertainty_notes=notes,
        had_citation_markers=_has_citation_markers(full_text),
    )

#!/usr/bin/env python3
"""Real LLM connectivity + generation smoke test — see Prompt 11.5 "Real
LM Studio smoke test". Instantiates the real configured provider (via
app.rag.llm_provider — the same code path answer generation uses, no
mocking), checks connectivity, and performs one minimal real generation
call. Never prints the configured API key.

Usage:
    python scripts/check_llm.py

Exits 0 on success, 1 on any failure.
"""

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from pydantic import BaseModel  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.rag.exceptions import LLMAnalysisError  # noqa: E402
from app.rag.llm_provider import (  # noqa: E402
    LangChainStructuredLLMProvider,
    normalize_llm_provider,
)

_SYSTEM_PROMPT = (
    "You are a connectivity test. Reply with exactly the sentence: "
    "CodeGraph AI LLM connection successful."
)
_USER_PROMPT = "Reply with the exact sentence you were told to reply with."


class _ConnectivityCheckOutput(BaseModel):
    message: str


async def main() -> int:
    settings = get_settings()
    provider_name = normalize_llm_provider(settings.llm_provider)

    provider_label = (
        "LM Studio / OpenAI-compatible" if provider_name == "openai_compatible" else "Anthropic"
    )
    print("CodeGraph AI — LLM check")
    print(f"LLM provider: {provider_label}")
    if provider_name == "openai_compatible":
        print(f"Base URL: {settings.llm_base_url or '(not set)'}")
    print(f"Model: {settings.llm_model or '(not set)'}")
    print()

    provider = LangChainStructuredLLMProvider(
        settings,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=0.0,
        max_tokens=64,
    )

    try:
        result = await provider.generate_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_USER_PROMPT,
            output_schema=_ConnectivityCheckOutput,
        )
    except LLMAnalysisError as exc:
        print("Connectivity: FAIL")
        print("Generation: FAIL")
        print()
        print(f"Reason: {exc}")
        return 1

    print("Connectivity: PASS")
    print("Generation: PASS")
    print()
    print("Response:")
    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

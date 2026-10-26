#!/usr/bin/env python3
"""End-to-end backend capability check against the seeded demo repository
— see the integration-reliability task's "Demo verification script".

Requires scripts/seed_demo_repository.py to have been run first. Exits
non-zero (and never hides a failure) if any check fails — Neo4j-dependent
checks (graph caller lookup, impact analysis) report [FAIL] with a clear
reason rather than being silently skipped when Neo4j is unavailable, since
this script's purpose is to say plainly whether the backend is demo-ready
right now.

Usage:
    python scripts/run_demo_checks.py
"""

import asyncio
import re
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_session_factory, init_db  # noqa: E402
from app.domain.rag.enums import RetrievalMode  # noqa: E402
from app.domain.repositories.store import list_repositories  # noqa: E402
from app.graph.neo4j_client import get_neo4j_client  # noqa: E402
from app.impact import service as impact_service  # noqa: E402
from app.impact.exceptions import ImpactError  # noqa: E402
from app.indexing.chroma_store import get_vector_store  # noqa: E402
from app.indexing.sentence_transformer_provider import get_embedding_provider  # noqa: E402
from app.ingestion import analysis_state_service as state_service  # noqa: E402
from app.rag import answer_service  # noqa: E402
from app.rag.hybrid_retriever import retrieve  # noqa: E402

DEMO_REPOSITORY_NAME = "codegraph-demo-python-app"
TARGET_QUALIFIED_NAME = "app.services.auth_service.AuthService.login"


class _SmartFakeLLMProvider:
    """No real Anthropic API key is configured for this script — this
    inspects the real evidence pool it's given and cites whatever is
    actually there, still exercising the real citation-validation
    pipeline end-to-end (see the answer-generation task's manual
    verification for the same disclosed technique)."""

    async def generate_structured(self, *, system_prompt, user_prompt, output_schema):
        ids = re.findall(r"\[(E\d+)\]", user_prompt)
        unique_ids = list(dict.fromkeys(ids))[:2]
        if not unique_ids:
            return output_schema(answer="Not enough evidence.", sufficient_evidence=False)
        cites = " ".join(f"[{eid}]" for eid in unique_ids)
        return output_schema(
            answer=f"Based on the repository evidence, {cites}.", sufficient_evidence=True
        )

    async def generate_text_stream(self, *, system_prompt, user_prompt):  # pragma: no cover
        yield "unused"


def _find_demo_repository_id(session) -> str | None:
    matches = [r for r in list_repositories(session) if r.name == DEMO_REPOSITORY_NAME]
    return matches[0].repository_id if matches else None


async def main() -> int:
    init_db()
    settings = get_settings()
    session = get_session_factory()()
    neo4j_client = get_neo4j_client()
    embedding_provider = get_embedding_provider()
    vector_store = get_vector_store()

    results: list[tuple[str, bool, str | None]] = []

    def check(name: str, passed: bool, reason: str | None = None) -> None:
        results.append((name, passed, reason))

    repository_id = _find_demo_repository_id(session)
    if repository_id is None:
        print("[FAIL] repository ready")
        print("Reason: no demo repository found — run scripts/seed_demo_repository.py first.")
        session.close()
        return 1

    state = state_service.get_state(session, repository_id)
    check(
        "repository ready",
        state is not None and state.overall_status in ("READY", "PARTIAL"),
        None if state else "no analysis state found",
    )
    check(
        "parser ready",
        state is not None and state.parser_status == "READY",
        state.parser_status if state else "no state",
    )
    check(
        "graph ready",
        state is not None and state.graph_status == "READY",
        state.graph_status if state else "no state",
    )
    check(
        "vector ready",
        state is not None and state.vector_status == "READY",
        state.vector_status if state else "no state",
    )

    # --- semantic retrieval (vector-only) -----------------------------------
    try:
        vector_result = await retrieve(
            repository_id=repository_id,
            question="Where is authentication implemented?",
            mode=RetrievalMode.VECTOR,
            top_k=None,
            settings=settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )
        check(
            "semantic retrieval",
            len(vector_result.evidence) > 0,
            None if vector_result.evidence else "no evidence returned",
        )
    except Exception as exc:  # noqa: BLE001
        check("semantic retrieval", False, str(exc))

    # --- graph caller lookup -------------------------------------------------
    try:
        graph_result = await retrieve(
            repository_id=repository_id,
            question="Which functions call AuthService.login?",
            mode=RetrievalMode.GRAPH,
            top_k=None,
            settings=settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )
        check(
            "graph caller lookup",
            len(graph_result.evidence) > 0,
            None if graph_result.evidence else "no evidence returned (see diagnostics.warnings)",
        )
    except Exception as exc:  # noqa: BLE001
        check("graph caller lookup", False, str(exc))

    # --- hybrid retrieval ------------------------------------------------------
    try:
        hybrid_result = await retrieve(
            repository_id=repository_id,
            question="Explain AuthService.login in simple terms.",
            mode=RetrievalMode.HYBRID,
            top_k=None,
            settings=settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )
        check(
            "hybrid retrieval",
            len(hybrid_result.evidence) > 0,
            None if hybrid_result.evidence else "no evidence returned",
        )
    except Exception as exc:  # noqa: BLE001
        check("hybrid retrieval", False, str(exc))

    # --- grounded citations (fake LLM — no API key configured) -----------------
    try:
        answer = await answer_service.answer_question(
            session,
            repository_id=repository_id,
            question="Explain AuthService.login in simple terms.",
            retrieval_mode=RetrievalMode.HYBRID,
            conversation_id=None,
            settings=settings,
            neo4j_client=neo4j_client,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=_SmartFakeLLMProvider(),
            query_analyzer_llm_provider=None,
        )
        check(
            "grounded citations (fake LLM)",
            (not answer.abstained) and len(answer.citations) > 0,
            None if answer.citations else f"abstained={answer.abstained}, no citations",
        )
    except Exception as exc:  # noqa: BLE001
        check("grounded citations (fake LLM)", False, str(exc))

    # --- impact analysis ---------------------------------------------------------
    try:
        impact_service.get_impact_analysis(
            neo4j_client,
            settings,
            repository_id=repository_id,
            qualified_name=TARGET_QUALIFIED_NAME,
        )
        check("impact analysis", True, None)
    except ImpactError as exc:
        check("impact analysis", False, str(exc))
    except Exception as exc:  # noqa: BLE001
        check("impact analysis", False, str(exc))

    print()
    all_passed = True
    for name, passed, reason in results:
        if passed:
            print(f"[PASS] {name}")
        else:
            all_passed = False
            print(f"[FAIL] {name}")
            if reason:
                print(f"Reason: {reason}")
    print()
    print(
        "Demo backend ready."
        if all_passed
        else "Demo backend NOT fully ready — see failures above."
    )

    session.close()
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Startup configuration validation — see Prompt 11.5 "Environment
validation": "If LLM_PROVIDER=lmstudio and LLM_BASE_URL missing, return a
useful configuration error... Do not crash with a deep LangChain/OpenAI
SDK traceback."

Every check here is advisory only: it logs a clear, actionable warning and
lets the process start anyway. A stopped LM Studio server or an
unreachable Neo4j at boot are normal, recoverable states in this
application (see app/main.py's existing best-effort Neo4j schema
initialization, which follows the same philosophy) — actually contacting
Neo4j/Chroma/the LLM/the embedding model is the job of
app/core/dependencies/status_service.py (GET /health/ready) and the
scripts/check_*.py smoke tests, not this module. Nothing here makes a
network call or loads a model.

Never logs a secret value itself — only whether one looks configured (see
SECURITY.md and this project's "Do not validate secrets by printing
them.").
"""

import logging
from pathlib import Path

from app.core.config import Settings
from app.rag.llm_provider import normalize_llm_provider

logger = logging.getLogger(__name__)


def check_configuration(settings: Settings) -> list[str]:
    """Returns every warning message (also logged as it's produced) —
    returned as a list mainly so tests/callers can assert on the content
    without parsing log output."""
    warnings: list[str] = []

    provider = normalize_llm_provider(settings.llm_provider)
    if provider == "openai_compatible":
        if not settings.llm_base_url:
            warnings.append(
                "LLM_PROVIDER is set to a local/OpenAI-compatible provider "
                "(openai_compatible/lmstudio), but LLM_BASE_URL is not set — answer "
                "generation will fail until it is configured. See docs/LOCAL_LLM_SETUP.md."
            )
        if not settings.llm_model:
            warnings.append(
                "Local LLM model is not configured — set LLM_MODEL to the model "
                "identifier currently loaded and served by LM Studio. See "
                "docs/LOCAL_LLM_SETUP.md."
            )
    else:
        if not settings.llm_api_key or settings.llm_api_key == "changeme":
            warnings.append(
                "LLM_API_KEY looks unconfigured (still the placeholder value) — answer "
                "generation will fail until a real API key is set, or switch "
                "LLM_PROVIDER to a local provider (lmstudio) instead."
            )
        if not settings.llm_model:
            warnings.append("LLM_MODEL is not configured.")

    if not settings.neo4j_uri:
        warnings.append("NEO4J_URI is empty — the knowledge graph will be unavailable.")
    if not settings.neo4j_username or not settings.neo4j_password:
        warnings.append("NEO4J_USERNAME and/or NEO4J_PASSWORD are not fully set.")

    if not settings.embedding_model_name:
        warnings.append(
            "EMBEDDING_MODEL_NAME is empty — semantic retrieval will be unavailable."
        )

    for path_value, label in (
        (settings.ingestion_workspace_dir, "INGESTION_WORKSPACE_DIR"),
        (settings.ingestion_allowed_base_dir, "INGESTION_ALLOWED_BASE_DIR"),
    ):
        try:
            Path(path_value).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            warnings.append(
                f"{label} could not be created/is not writable ({type(exc).__name__})."
            )

    for message in warnings:
        logger.warning("Configuration check: %s", message)
    if not warnings:
        logger.info("Configuration check: no issues found.")
    return warnings

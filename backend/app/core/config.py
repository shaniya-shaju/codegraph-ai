"""Application configuration.

All settings are read from environment variables (see ``.env.example`` at
the repository root). Nothing here should hardcode a value that differs
between development and production — that distinction belongs in the
environment, not in code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to the repository root regardless of process CWD — a relative
# ".env" here would instead resolve against CWD, which silently stops
# matching the repo-root .env as soon as the backend is launched from
# backend/ (e.g. `cd backend && uvicorn app.main:app`, as documented in
# the Makefile's run-backend target). The same CWD problem applies to every
# relative filesystem-path setting below (database_url's sqlite path,
# chroma_persist_directory, the ingestion directories) — see
# _anchor_relative_path_settings / _anchor_sqlite_database_url.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT_ENV_FILE = _REPO_ROOT / ".env"
_SQLITE_URL_PREFIX = "sqlite:///"


def _resolve_repo_relative(value: str) -> str:
    """Anchor a relative filesystem path to the repository root instead of
    the process's current working directory. An already-absolute path
    (as Docker Compose's environment: block always provides) passes
    through unchanged."""
    path = Path(value)
    if path.is_absolute():
        return value
    return str((_REPO_ROOT / path).resolve())


class Settings(BaseSettings):
    """Typed view over the environment variables in ``.env.example``."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Backend service ---
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_allowed_origins: str = "http://localhost:5173"

    # --- Authentication ---
    auth_secret_key: str = ""
    auth_token_expiry_hours: int = 12

    # --- Application database ---
    database_url: str = "sqlite:///./data/codegraph.db"

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "changeme"
    neo4j_database: str = "neo4j"
    neo4j_connection_timeout_seconds: int = 10
    neo4j_max_connection_pool_size: int = 50

    # --- Neo4j fail-fast (see app/core/dependencies/circuit_breaker.py and
    # app/graph/neo4j_client.py) — a driver-level transaction-retry loop
    # (default ~30s) was the actual source of the "30-55 second wait when
    # Neo4j is unavailable" problem; NEO4J_OPERATION_TIMEOUT_SECONDS bounds
    # that per-call, and the circuit breaker settings below bound how many
    # such (still-bounded) attempts happen before subsequent calls fail
    # immediately with no I/O at all. ---
    neo4j_operation_timeout_seconds: int = 3
    neo4j_circuit_failure_threshold: int = 3
    neo4j_circuit_cooldown_seconds: float = 30.0

    # --- Graph query bounds (see ARCHITECTURE.md "Change-impact-analysis
    # design"; all traversal endpoints must enforce these) ---
    graph_default_traversal_depth: int = 1
    graph_max_traversal_depth: int = 5
    graph_max_nodes: int = 500
    graph_max_relationships: int = 1000
    graph_symbol_search_default_limit: int = 20
    graph_symbol_search_max_limit: int = 100

    # --- ChromaDB (see indexing/chroma_store.py) ---
    chroma_persist_directory: str = "./data/chroma"
    # Prefixed onto every sanitized repository_id to form a collection name
    # (see indexing/metadata.py's `sanitize_collection_name`) — never a raw
    # repository name.
    chroma_collection_prefix: str = "codegraph"
    chroma_host: str | None = None
    chroma_port: int | None = None

    # --- LLM provider (synthesis/summarization only — see AGENTS.md rule 2).
    # See app/rag/llm_provider.py's `normalize_llm_provider` — "anthropic"
    # uses the cloud Anthropic API; "openai_compatible" (alias:
    # "lmstudio") talks to any OpenAI-compatible chat-completions server
    # via `llm_base_url`, which is how local LM Studio support is
    # implemented (see docs/LOCAL_LLM_SETUP.md) — no separate
    # LM-Studio-specific client exists. ---
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    llm_api_key: str = "changeme"
    # Only meaningful for "openai_compatible"/"lmstudio" — e.g.
    # http://localhost:1234/v1 (backend on host) or
    # http://host.docker.internal:1234/v1 (backend in Docker Desktop
    # talking to LM Studio on the host). Ignored for "anthropic".
    llm_base_url: str | None = None
    # Low by default — grounded answers should be conservative, not
    # creative (see the answer-generation task: "Default answer
    # temperature should be low").
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 1024
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 2
    # Bounds the connectivity check performed by GET /health/ready for an
    # "openai_compatible"/"lmstudio" provider (a models-list request) —
    # deliberately short so a stopped/unreachable local LLM server never
    # makes readiness slow (see "LLM connectivity check": "Use a short
    # timeout."). Not used for "anthropic" — see check_llm's docstring for
    # why that path never makes a live network call.
    llm_health_check_timeout_seconds: float = 2.0

    # --- Grounded answer generation (see app/rag/answer_service.py) ---
    # Evidence whose top hybrid_score falls below this is treated as too
    # weak to answer from — a pre-generation abstention signal.
    answer_min_evidence_relevance: float = 0.15
    answer_high_confidence_threshold: float = 0.7
    answer_medium_confidence_threshold: float = 0.4
    # How many ranked evidence items are actually shown to the LLM/made
    # citable — separate from RAG_MAX_EVIDENCE_ITEMS (retrieval's own
    # budget), since not all retrieved evidence needs to reach the prompt.
    answer_max_citations: int = 8
    # How many prior conversation turns are considered for follow-up
    # question resolution (see app/rag/conversation_context.py).
    conversation_max_turns: int = 10

    # --- Embedding provider (see indexing/embedding_provider.py). The
    # sentence_transformers provider is fully local — no repository code
    # is ever sent to an external API with this default (see SECURITY.md
    # and AGENTS.md rule 11/12). embedding_api_key/base_url only matter
    # for a possible future OpenAI-compatible/Ollama provider. ---
    embedding_provider: str = "sentence_transformers"
    # sentence-transformers/all-MiniLM-L6-v2: a standard, widely-cached
    # model with no custom Hub code, so it needs no EMBEDDING_TRUST_REMOTE_CODE
    # opt-in — chosen as the transfer-ready default for exactly that reason
    # (see docs/TROUBLESHOOTING.md "trust_remote_code problem": a
    # custom-code model like jinaai/jina-embeddings-v2-base-code can
    # silently load in a degraded, partially-randomly-initialized state on
    # some transformers versions when EMBEDDING_TRUST_REMOTE_CODE is left
    # false, rather than failing loudly — avoided entirely by defaulting to
    # a model that never needs that flag). 384-dim output vs. 768 for the
    # jina model — lower retrieval quality on code-specific queries, but a
    # safer, simpler default for a first-time setup. Any
    # sentence-transformers-compatible model id works — see .env.example.
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 16
    embedding_normalize: bool = True
    embedding_max_sequence_length: int = 4096
    embedding_trust_remote_code: bool = False
    embedding_api_key: str | None = None
    embedding_api_base_url: str | None = None

    # --- Vector retrieval bounds (see indexing/retrieval_service.py) ---
    vector_default_top_k: int = 8
    vector_max_top_k: int = 30
    vector_min_score: float = 0.0

    # --- Syntax-aware chunking (see indexing/chunker.py) ---
    code_chunk_max_characters: int = 4000
    code_chunk_max_lines: int = 200
    code_chunk_context_lines: int = 3

    # --- Indexing ---
    indexing_batch_size: int = 32

    # --- Ingestion safety limits (see SECURITY.md) ---
    ingestion_allowed_base_dir: str = "./data/allowed_repos"
    ingestion_workspace_dir: str = "./data/workspaces"
    ingestion_clone_timeout_seconds: int = 120
    ingestion_max_repo_size_mb: int = 500
    # Cap on the raw uploaded .zip file itself, checked while streaming the
    # upload to disk — distinct from ingestion_max_repo_size_mb, which caps
    # the *extracted* (or cloned) content size.
    ingestion_max_upload_size_mb: int = 50

    # --- Remote repository URL cloning (see app/ingestion/git_clone.py and
    # SECURITY.md "Repository acquisition safety"). A separate, narrower
    # safety layer on top of the general git-clone support above: this
    # restricts *which hosts* may be cloned from at all, and can disable
    # URL-based cloning entirely. Private repositories and SSH URLs are
    # never supported (public HTTPS only, enforced unconditionally in
    # app/ingestion/git_clone.py regardless of this section). ---
    # Kill switch — set false to disable the clone endpoint entirely
    # (returns a clear, typed error rather than a generic 404/500).
    repo_url_clone_enabled: bool = True
    # Comma-separated exact hostnames (case-insensitive) — see
    # `repo_clone_allowed_hosts_set` below. Deliberately narrow by
    # default; widen only if you understand the SSRF-adjacent risk of
    # letting this server fetch from arbitrary hosts (see SECURITY.md).
    repo_clone_allowed_hosts: str = "github.com,gitlab.com"
    # Shallow-clone depth passed to `git clone --depth`. 1 is sufficient
    # for parsing/indexing (full history is never needed) and keeps
    # clones fast and small.
    repo_clone_depth: int = 1

    # --- Change-impact analysis defaults (legacy — read only by
    # app/rag/retrieval_planner.py to suggest a graph-retrieval depth for
    # IMPACT_ANALYSIS-intent questions; NOT used by the deterministic
    # impact-analysis engine itself, which uses the IMPACT_* settings
    # below. Kept as-is to avoid an out-of-scope change to Prompt 7/8's
    # retrieval planner — see the impact-analysis task's final report.) ---
    impact_analysis_default_max_depth: int = 3

    # --- Deterministic change-impact-analysis engine (see app/impact/) ---
    impact_default_depth: int = 2
    impact_max_depth: int = 5
    impact_default_max_nodes: int = 200
    impact_max_nodes: int = 1000
    impact_max_paths: int = 100

    # Structural risk-score weights (0-100 total; see app/impact/signals.py
    # and risk_scorer.py). These are initial, UNTUNED heuristics — see the
    # impact-analysis task: "These numbers are initial heuristics and must
    # be clearly documented as untuned." Never treat the resulting score as
    # a probability of failure.
    impact_weight_direct_callers: float = 15.0
    impact_weight_transitive_dependents: float = 15.0
    impact_weight_affected_files: float = 10.0
    impact_weight_api_exposure: float = 20.0
    impact_weight_cross_module: float = 10.0
    impact_weight_external_dependency: float = 5.0
    impact_weight_inheritance: float = 10.0
    impact_weight_centrality: float = 10.0
    impact_weight_test_signal: float = 5.0

    # Reference counts used to normalize each signal's raw count into
    # [0.0, 1.0] before weighting (normalized = min(raw / reference, 1.0)) —
    # also untuned heuristics, see above.
    impact_reference_direct_callers: float = 5.0
    impact_reference_transitive_dependents: float = 15.0
    impact_reference_affected_files: float = 8.0
    impact_reference_api_endpoints: float = 2.0
    impact_reference_cross_module: float = 5.0
    impact_reference_external_dependencies: float = 3.0
    impact_reference_inheritance: float = 3.0
    impact_reference_centrality: float = 10.0

    # Risk-level thresholds (score >= threshold maps to that level or
    # higher) — configurable, never probabilities.
    impact_risk_medium_threshold: float = 25.0
    impact_risk_high_threshold: float = 50.0
    impact_risk_critical_threshold: float = 75.0

    # --- Hybrid retrieval / query analysis (see app/rag/) ---
    # heuristic | llm | hybrid — the deterministic analyzer always runs;
    # this only controls whether/how the optional LLM strategy is used
    # (see app/rag/query_analyzer.py). An LLM outage never breaks
    # retrieval regardless of this setting.
    query_analyzer_mode: str = "hybrid"
    query_analyzer_llm_enabled: bool = False
    query_analyzer_timeout_seconds: int = 10

    # How many ranked candidate symbols SymbolRetriever considers per query.
    rag_symbol_candidate_limit: int = 5

    # Context-fusion ranking weights (see app/rag/context_fusion.py) —
    # heuristic ranking-signal weights, not probabilities.
    hybrid_vector_weight: float = 0.45
    hybrid_exact_weight: float = 0.25
    hybrid_graph_weight: float = 0.20
    hybrid_intent_weight: float = 0.10

    # Context budget applied before (future) LLM answer generation — see
    # app/rag/context_budget.py.
    rag_max_context_characters: int = 12000
    rag_max_evidence_items: int = 20
    rag_max_evidence_per_file: int = 4
    rag_max_graph_evidence: int = 10
    rag_max_vector_evidence: int = 10

    @field_validator(
        "chroma_persist_directory", "ingestion_allowed_base_dir", "ingestion_workspace_dir"
    )
    @classmethod
    def _anchor_relative_path_settings(cls, value: str) -> str:
        return _resolve_repo_relative(value)

    @field_validator("database_url")
    @classmethod
    def _anchor_sqlite_database_url(cls, value: str) -> str:
        """Anchor a relative sqlite:/// path to the repository root — see
        _resolve_repo_relative. Non-sqlite URLs (e.g. postgresql://...), an
        empty path, and sqlite:///:memory: are returned unchanged."""
        if not value.startswith(_SQLITE_URL_PREFIX):
            return value
        db_path = value.removeprefix(_SQLITE_URL_PREFIX)
        if db_path in ("", ":memory:") or Path(db_path).is_absolute():
            return value
        resolved = (_REPO_ROOT / db_path).resolve().as_posix()
        return f"{_SQLITE_URL_PREFIX}{resolved}"

    @property
    def cors_origins(self) -> list[str]:
        """``cors_allowed_origins`` split into a list for CORS middleware."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def repo_clone_allowed_hosts_set(self) -> frozenset[str]:
        """``repo_clone_allowed_hosts`` split into a lowercase, trimmed set
        for exact hostname matching (see app.ingestion.git_clone.validate_allowed_host)."""
        return frozenset(
            host.strip().lower()
            for host in self.repo_clone_allowed_hosts.split(",")
            if host.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, suitable for use as a FastAPI dependency."""
    return Settings()

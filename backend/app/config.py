"""Runtime configuration, read once from the environment.

Two LLM providers are supported. Gemini is reached through Google's
OpenAI-compatible endpoint, so a single client and one set of call sites serve
both: only the base URL, the key and the model names differ.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to this file, not to the working directory. A bare ".env" is
# resolved against wherever the process happens to have been started, so
# `uvicorn` launched from backend/ found the key while a script run from the
# repo root silently did not - and the only symptom was every request behaving
# as though no provider were configured.
ENV_FILE: Final = Path(__file__).resolve().parent.parent / ".env"

GEMINI_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Per-provider model defaults, applied when the matching env var is left blank.
_MODEL_DEFAULTS: Final[dict[str, dict[str, str]]] = {
    "openai": {
        "chat_model": "gpt-4o",
        "vision_model": "gpt-4o",
        "extraction_model": "gpt-4o-mini",
        "crawler_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
    },
    "gemini": {
        # Lite models on purpose. The free tier caps the newest full-size flash
        # models at 20 requests per *day* (gemini-3.6-flash), which a single
        # afternoon of testing exhausts; the lite tier is far more generous and
        # handles streaming, JSON mode and transcript OCR just as well here.
        #
        # Chat and extraction also sit on different models: quota is metered per
        # model, and every turn makes one call to each, so splitting them keeps
        # a normal conversation clear of both the per-minute and daily caps.
        "chat_model": "gemini-3.5-flash-lite",
        "vision_model": "gemini-3.5-flash-lite",
        "extraction_model": "gemini-3.1-flash-lite",
        # 3.5, not 3.1: the 3.1 lite tier returns a persistent 503 "high
        # demand" for the long extraction prompts this pipeline sends.
        "crawler_model": "gemini-3.5-flash-lite",
        # Verified against the live API: text-embedding-004 is not served to
        # new keys, and gemini-embedding-001 honours an explicit `dimensions`,
        # so both providers can be pinned to the same width.
        "embedding_model": "gemini-embedding-001",
    },
}


# Gemini 3 models spend part of the output budget on internal reasoning before
# emitting any text, so a cap sized for OpenAI truncates the visible reply (or
# yields an empty one). The system prompt, not this number, keeps replies short.
_MAX_TOKEN_DEFAULTS: Final[dict[str, int]] = {"openai": 400, "gemini": 1500}

# Embedding width per provider default. It must match the Qdrant collection:
# a collection created at one width rejects vectors of another, so changing the
# embedding model means recreating the collection.
_EMBEDDING_DIMENSIONS: Final[dict[str, int]] = {"openai": 1536, "gemini": 1536}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["openai", "gemini"] = "openai"

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    gemini_base_url: str = GEMINI_BASE_URL

    # Blank means "use the default for the active provider".
    chat_model: str = ""
    vision_model: str = ""
    extraction_model: str = ""
    chat_max_tokens: int = 0  # 0 = provider default

    # --- Document parsing --------------------------------------------------
    ocr_provider: Literal["vision", "llamaparse"] = "vision"
    llamaparse_api_key: str | None = None
    llamaparse_base_url: str = "https://api.cloud.llamaindex.ai/api/parsing"
    ocr_timeout_seconds: float = 120.0
    llamaparse_poll_interval: float = 2.0

    max_upload_bytes: int = Field(default=10 * 1024 * 1024)  # 10 MB
    allowed_upload_types: tuple[str, ...] = (
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
    )

    # --- Accounts -----------------------------------------------------------
    # Supabase project that owns the auth users and the chat history tables.
    supabase_url: str = ""
    # The anon/publishable key. Safe in a browser; it carries no privileges of
    # its own and is governed entirely by Row Level Security.
    supabase_anon_key: str = ""
    # Verifies the JWT signature. For a project using the legacy HS256 signing
    # secret this is that secret; projects on asymmetric keys are verified
    # against the published JWKS instead, which needs no secret here.
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    # The service-role key, used only by the backend to write chat history on a
    # student's behalf. It bypasses RLS, so it must never reach the browser -
    # see the note in migrations/001_chat_history_rls.sql.
    supabase_service_role_key: str = ""

    @property
    def auth_configured(self) -> bool:
        """True once a Supabase project is wired up.

        Auth is enforced only when it can be: with nothing configured the app
        runs exactly as it did before accounts existed, so a checkout without
        Supabase credentials is still a working app rather than a wall of 401s.
        """
        return bool(self.supabase_url) and bool(
            self.supabase_jwt_secret or self.supabase_jwks_url
        )

    @property
    def history_configured(self) -> bool:
        """True once chat history can actually be written."""
        return bool(self.supabase_url and self.supabase_service_role_key)

    # --- Phase 2: crawl, ingest, hybrid search -----------------------------
    # Postgres for the numeric/categorical filter, Qdrant for syllabus vectors.
    # 5433, not 5432: a native PostgreSQL service commonly owns 5432, and both
    # binding it surfaces as a password failure rather than a port conflict.
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5433/study_abroad"
    )
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "course_syllabi"

    # Blank means "use the default for the active provider" (see below).
    crawler_model: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0

    crawl_timeout_seconds: float = 120.0
    crawl_max_retries: int = 3
    # Hard cap on the candidate id list handed from Postgres to Qdrant. Qdrant
    # matches those ids with MatchAny, and an unbounded IN list would blow up
    # both the SQL plan and the filter payload.
    #
    # Raised from 500 to cover a whole country's catalogue in one pass.
    # Candidates are taken cheapest-first, so at 500 the cap was not a neutral
    # truncation: on this index Australia has 3,817 Master's, and 3,317 of them
    # - 87% - were dropped before similarity was ever computed, purely for
    # costing more than A$36,234. RMIT's Master of Communication Design scores
    # 0.720 against "Masters in Graphic Design in Australia", which would place
    # it second, and it was invisible at 2,355th cheapest.
    #
    # The failure mode was silent: the search returned plausible results, so
    # nothing looked wrong. Qdrant matches a 4k id list with MatchAny without
    # difficulty.
    max_sql_candidates: int = 4000
    search_top_k: int = 10

    # How relevant a programme must be before a student is shown it. Both are
    # cosine scores against the syllabus vector, and both were set by measuring
    # this index rather than guessed:
    #
    #   a subject with a real match   English Literature -> 0.647, then 0.555
    #   a subject with none           Medicine -> 0.541, Graphic Design -> 0.587
    #
    # So a genuine match sits above ~0.60 and is followed by a visible cliff,
    # while an absent subject produces a flat band in the low 0.5s. The floor
    # rejects the flat band; the margin trims the tail below the cliff.
    #
    # These are calibrated for the current embedding model. Changing
    # EMBEDDING_MODEL shifts the whole score distribution, so re-measure rather
    # than assuming they carry over.
    match_min_similarity: float = 0.60
    match_similarity_margin: float = 0.06

    # When the first search returns fewer than this, it is retried once with
    # neighbouring disciplines added and a lower floor. Widening only a thin
    # result keeps the precise case precise: measured here, mixing parent
    # terms into every query dropped a true match from 0.784 to 0.743 while
    # lifting an unrelated one from 0.612 to 0.658.
    match_min_results: int = 5
    match_fallback_similarity: float = 0.55

    # --- Session state -----------------------------------------------------
    redis_url: str | None = None  # falls back to in-process memory when unset
    session_ttl_seconds: int = 60 * 60 * 24  # 24h

    # --- HTTP --------------------------------------------------------------
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    @model_validator(mode="after")
    def _apply_provider_defaults(self) -> Settings:
        for field, default in _MODEL_DEFAULTS[self.llm_provider].items():
            if not getattr(self, field):
                setattr(self, field, default)
        if self.chat_max_tokens <= 0:
            self.chat_max_tokens = _MAX_TOKEN_DEFAULTS[self.llm_provider]
        if self.embedding_dimensions <= 0:
            self.embedding_dimensions = _EMBEDDING_DIMENSIONS[self.llm_provider]
        return self

    @property
    def api_key(self) -> str | None:
        """The key for the active provider."""
        if self.llm_provider == "gemini":
            return self.gemini_api_key
        return self.openai_api_key

    @property
    def base_url(self) -> str | None:
        """Base URL for the active provider; None means the OpenAI default."""
        if self.llm_provider == "gemini":
            return self.gemini_base_url
        return self.openai_base_url

    @property
    def llm_enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def vision_parser_name(self) -> str:
        """Value recorded on an ExtractedTranscript, so results stay traceable."""
        return "gemini_vision" if self.llm_provider == "gemini" else "gpt4o_vision"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

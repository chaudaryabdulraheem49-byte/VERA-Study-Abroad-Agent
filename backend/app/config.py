"""Runtime configuration, read once from the environment.

Two LLM providers are supported. Gemini is reached through Google's
OpenAI-compatible endpoint, so a single client and one set of call sites serve
both: only the base URL, the key and the model names differ.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

GEMINI_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Per-provider model defaults, applied when the matching env var is left blank.
_MODEL_DEFAULTS: Final[dict[str, dict[str, str]]] = {
    "openai": {
        "chat_model": "gpt-4o",
        "vision_model": "gpt-4o",
        "extraction_model": "gpt-4o-mini",
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
    },
}


# Gemini 3 models spend part of the output budget on internal reasoning before
# emitting any text, so a cap sized for OpenAI truncates the visible reply (or
# yields an empty one). The system prompt, not this number, keeps replies short.
_MAX_TOKEN_DEFAULTS: Final[dict[str, int]] = {"openai": 400, "gemini": 1500}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
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

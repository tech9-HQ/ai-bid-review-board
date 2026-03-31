"""
app/core/config.py
──────────────────
Centralised settings using pydantic-settings.
All config comes from environment variables / .env file.

Supports two AI backends (controlled by AI_BACKEND env var):
  "anthropic"  — Direct Anthropic API (default)
  "bedrock"    — AWS Bedrock (uses AWS Access Key + Secret)

Bedrock model IDs differ from Anthropic's — they follow the pattern:
  anthropic.claude-sonnet-4-6-20251115-v1:0
  anthropic.claude-opus-4-6-20251015-v1:0
These are set as the defaults when AI_BACKEND=bedrock.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_VERSION: str = "2.0.0"
    APP_TITLE: str = "Tech9Labs AI Bid Review Board"

    # ── AI Backend Selection ───────────────────────────────────────────────
    # Set to "bedrock" to use AWS Bedrock instead of direct Anthropic API
    AI_BACKEND: Literal["anthropic", "bedrock"] = "anthropic"

    # ── Anthropic Direct API (used when AI_BACKEND=anthropic) ─────────────
    ANTHROPIC_API_KEY: str = ""

    # ── AWS Bedrock credentials (used when AI_BACKEND=bedrock) ────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"

    # ── Claude Model Selection ─────────────────────────────────────────────
    # For AI_BACKEND=anthropic  →  use short model names
    #   claude-sonnet-4-6
    #   claude-opus-4-6
    #
    # For AI_BACKEND=bedrock    →  use Bedrock cross-region inference profile ARNs
    #   us.anthropic.claude-sonnet-4-6-20251115-v1:0
    #   us.anthropic.claude-opus-4-6-20251015-v1:0
    #
    # These defaults are set automatically by the validator below,
    # but you can override them explicitly in .env.

    CLAUDE_FAST_MODEL: str = ""   # resolved in validator
    CLAUDE_LEGAL_MODEL: str = ""  # resolved in validator

    AI_TEMPERATURE: float = 0.2
    AI_MAX_TOKENS: int = 4096

    # ── File Handling ──────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 50
    UPLOAD_DIR: str = "./uploads"
    OUTPUT_DIR: str = "./outputs"

    # ── Rate Limiting ──────────────────────────────────────────────────────
    MAX_CONCURRENT_JOBS: int = 3
    RATE_LIMIT_PER_MINUTE: int = 10

    # ── Observability ──────────────────────────────────────────────────────
    SENTRY_DSN: str = ""

    # ── CORS ───────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # ── Validators ─────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def resolve_models_and_credentials(self) -> "Settings":
        """
        1. Set default model IDs based on AI_BACKEND if not explicitly set.
        2. Validate that required credentials exist for the chosen backend.
        """
        # ── Resolve default model IDs ──────────────────────────────────────
        if self.AI_BACKEND == "anthropic":
            if not self.CLAUDE_FAST_MODEL:
                self.CLAUDE_FAST_MODEL = "claude-sonnet-4-6"
            if not self.CLAUDE_LEGAL_MODEL:
                self.CLAUDE_LEGAL_MODEL = "claude-opus-4-6"
        else:  # bedrock
            if not self.CLAUDE_FAST_MODEL:
                self.CLAUDE_FAST_MODEL = "us.anthropic.claude-sonnet-4-6-20251115-v1:0"
            if not self.CLAUDE_LEGAL_MODEL:
                self.CLAUDE_LEGAL_MODEL = "us.anthropic.claude-opus-4-6-20251015-v1:0"

        # ── Validate credentials ───────────────────────────────────────────
        if self.AI_BACKEND == "anthropic" and not self.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is required when AI_BACKEND=anthropic"
            )
        if self.AI_BACKEND == "bedrock":
            if not self.AWS_ACCESS_KEY_ID or not self.AWS_SECRET_ACCESS_KEY:
                raise ValueError(
                    "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required "
                    "when AI_BACKEND=bedrock"
                )

        return self

    @field_validator("AI_TEMPERATURE")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("AI_TEMPERATURE must be between 0.0 and 1.0")
        return v

    @field_validator("AI_MAX_TOKENS")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        if not 256 <= v <= 8192:
            raise ValueError("AI_MAX_TOKENS must be between 256 and 8192")
        return v

    # ── Computed Properties ────────────────────────────────────────────────

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        return Path(self.UPLOAD_DIR)

    @property
    def output_path(self) -> Path:
        return Path(self.OUTPUT_DIR)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def using_bedrock(self) -> bool:
        return self.AI_BACKEND == "bedrock"

    def ensure_dirs(self) -> None:
        """Create upload/output directories if they don't exist."""
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self.output_path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — call this everywhere."""
    return Settings()


# Module-level convenience alias
settings = get_settings()
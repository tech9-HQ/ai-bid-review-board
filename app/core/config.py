"""
app/core/config.py
─────────────────
Centralised settings loaded from environment / .env file.
All modules import `settings` from here — never read os.getenv() directly.
"""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_VERSION: str = "1.0.0"
    SECRET_KEY: str = "change-me"

    # ── AI Providers ─────────────────────────────────────────────────────────
    OPENAI_API_KEY: str
    ANTHROPIC_API_KEY: str | None = None  # Optional — Stage 5 legal review skipped if absent

    OPENAI_AUDIT_MODEL: str = "gpt-4o"
    OPENAI_REWRITE_MODEL: str = "gpt-4o"
    CLAUDE_LEGAL_MODEL: str = "claude-opus-4-6"
    AI_TEMPERATURE: float = 0.2
    AI_MAX_TOKENS: int = 4096

    # ── File Storage ─────────────────────────────────────────────────────────
    UPLOAD_DIR: Path = Path("./uploads")
    OUTPUT_DIR: Path = Path("./outputs")
    MAX_UPLOAD_SIZE_MB: int = 50

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # ── Sentry ───────────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def anthropic_available(self) -> bool:
        """True only when a real Anthropic key is configured."""
        return bool(self.ANTHROPIC_API_KEY and self.ANTHROPIC_API_KEY.startswith("sk-ant-"))

    def ensure_dirs(self) -> None:
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
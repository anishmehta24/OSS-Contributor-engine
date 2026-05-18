"""Centralized, typed config. Loaded once at import time.

Usage:
    from app.core.config import settings
    settings.github_token
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- GitHub ---
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # --- LLM providers ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")

    # --- Embeddings ---
    # "local" = sentence-transformers on CPU (free, no rate limits, ~384-dim)
    # "voyage" = Voyage AI hosted (better quality, 1024-dim, needs $5 prepaid)
    embedder_backend: str = Field(default="local", alias="EMBEDDER_BACKEND")
    embedder_model: str = Field(default="", alias="EMBEDDER_MODEL")
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")

    # --- OAuth (Batch 13) ---
    github_oauth_client_id: str = Field(default="", alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: str = Field(default="", alias="GITHUB_OAUTH_CLIENT_SECRET")
    oauth_redirect_uri: str = Field(
        default="http://localhost:8000/auth/callback",
        alias="OAUTH_REDIRECT_URI",
    )
    oauth_post_login_redirect: str = Field(
        default="http://localhost:8501",
        alias="OAUTH_POST_LOGIN_REDIRECT",
    )
    # SESSION_SECRET must be a Fernet-compatible key (44 chars base64).
    # Generate with: uv run python scripts/gen_session_secret.py
    session_secret: str = Field(default="", alias="SESSION_SECRET")
    # Cookie/session lifetime in seconds (default 7 days)
    session_max_age_s: int = Field(default=7 * 24 * 3600, alias="SESSION_MAX_AGE_S")

    # --- App ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(default="sqlite:///./oss_engine.db", alias="DATABASE_URL")

    # ------------------------------------------------------------------

    @property
    def has_github(self) -> bool:
        return bool(self.github_token) and not self.github_token.endswith("REPLACE_ME")

    @property
    def has_any_llm(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)

    @property
    def embedder_dim(self) -> int:
        """Dimension of the embeddings the chosen backend produces.
        Used to size the vec0 virtual tables — must match exactly."""
        if self.embedder_backend == "voyage":
            return 1024
        # local default model: all-MiniLM-L6-v2 = 384 dims
        return 384

    @property
    def embedder_ready(self) -> bool:
        if self.embedder_backend == "voyage":
            return bool(self.voyage_api_key)
        return True  # local always available once installed

    @property
    def has_oauth(self) -> bool:
        return bool(
            self.github_oauth_client_id
            and self.github_oauth_client_secret
            and self.session_secret
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

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
        default="http://localhost:3000/auth/handoff",
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

    # --- Sandbox (v3 — Autonomous Contribution Pilot) ---
    # The Docker image agent code runs inside. Built once via
    # `python -m app.sandbox build`. Override only if you've rebuilt against
    # a different tag.
    sandbox_image: str = Field(
        default="oss-engine-sandbox:latest", alias="SANDBOX_IMAGE",
    )
    # Per-investigation workspaces are nested under this dir on the host.
    sandbox_workspace_root: str = Field(
        default=".sandbox", alias="SANDBOX_WORKSPACE_ROOT",
    )
    # Hard caps. Docker syntax for memory ("1g", "512m"), float for cpus.
    sandbox_memory_limit: str = Field(default="1g", alias="SANDBOX_MEMORY_LIMIT")
    sandbox_cpus: float = Field(default=1.0, alias="SANDBOX_CPUS")
    # Default command timeout. Individual `runner.run(... timeout_s=N)` calls
    # can override.
    sandbox_default_timeout_s: int = Field(
        default=300, alias="SANDBOX_DEFAULT_TIMEOUT_S",
    )

    # --- Safety rails (Batch 37) ---
    # Per-user lifetime LLM spend ceiling, in USD. The pilot (the most
    # expensive op) refuses to start once a user crosses this. 0 = no cap.
    max_user_cost_usd: float = Field(default=5.0, alias="MAX_USER_COST_USD")
    # Comma-separated owners or owner/repo slugs the pilot will NOT fork,
    # push to, or open PRs against. Use for repos whose maintainers have
    # opted out of AI-generated contributions. Matching is case-insensitive
    # and supports both "owner" (blocks all their repos) and "owner/repo".
    pilot_refuse_list: str = Field(default="", alias="PILOT_REFUSE_LIST")

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

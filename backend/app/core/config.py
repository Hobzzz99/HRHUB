"""Application configuration, loaded from environment variables.

All runtime knobs live here so nothing is hard-coded. See `.env.example` for the
full documented list of settings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ProviderName = Literal["mock", "apify", "playwright"]
Toggle = Literal["on", "off"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # NoDecode: let the validator below split a comma-separated env string,
    # instead of pydantic-settings trying to JSON-decode it.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Database ---
    database_url: str = (
        "postgresql+psycopg://candidates:candidates@localhost:5432/candidates"
    )

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # Run tasks inline in-process (no broker) — handy for local dev/tests.
    celery_task_always_eager: bool = False

    # --- Provider ---
    provider: ProviderName = "mock"
    profile_ttl_days: int = 7
    scrape_min_delay_ms: int = 1500
    scrape_max_delay_ms: int = 4000
    scrape_max_profiles: int = 25
    # Headless is easily detected by LinkedIn. Run headed locally (a real window
    # opens; you can solve a CAPTCHA if shown). Keep True on a headless server.
    scrape_headless: bool = True
    # When headed and LinkedIn shows a security checkpoint, how long to wait for
    # you to solve it by hand before giving up. Headless runs never wait (nobody
    # is there to solve it) and fail immediately.
    scrape_challenge_timeout_s: int = 180
    # Where Playwright browser binaries live. Leave empty to use Playwright's
    # default (correct in the Docker worker image); set it when browsers were
    # installed to a custom path (e.g. a drive with free space).
    playwright_browsers_path: str = ""

    # --- Apify provider ---
    # LinkedIn data bought from Apify's Actors instead of scraped by us. No
    # LinkedIn account is involved, so there is nothing to get banned.
    apify_token: str = ""
    # Actor ids as "username/actor-name". Both defaults are **cookieless** — do
    # not swap in a cookie-based actor: passing a LinkedIn session cookie is what
    # puts an account at risk of the restriction this provider exists to avoid.
    apify_search_actor: str = "harvestapi/linkedin-profile-search"
    apify_profile_actor: str = "dev_fusion/linkedin-profile-scraper"
    # Actor runs are slow to start; a sync run caps out at 300s server-side.
    apify_timeout_s: int = 300
    # Dump every raw actor response to _debug/, not just unmappable ones.
    apify_debug_dump: bool = False

    # --- Encryption ---
    credential_enc_key: str = ""

    # --- AI matching ---
    ai_matching: Toggle = "off"
    anthropic_api_key: str = ""
    # Defaults to the most capable model; override with a cheaper one if desired.
    anthropic_model: str = "claude-opus-4-8"

    # --- Auth (Supabase) ---
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    auth_disabled: bool = True
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    dev_user_email: str = "dev@example.com"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string from the environment."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def ai_enabled(self) -> bool:
        return self.ai_matching == "on" and bool(self.anthropic_api_key)

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()

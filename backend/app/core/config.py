"""Application configuration, loaded from environment variables.

All runtime knobs live here so nothing is hard-coded. See `.env.example` for the
full documented list of settings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ProviderName = Literal["mock", "apify", "playwright", "linkedin", "indeed"]
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

    # --- Scraping rate limit (the real safety control) ---
    # Hard ceiling on profiles opened in any rolling window, counted across
    # searches AND worker restarts (see providers/rate_limit.py). Volume is what
    # gets an account flagged; keep this low.
    scrape_max_profiles_per_hour: int = 20
    scrape_rate_limit_window_s: int = 3600
    # How long a running search will sit waiting for the next slot before
    # stopping early and keeping what it already collected. Longer than this and
    # the search would just hold a browser open doing nothing.
    scrape_rate_limit_max_wait_s: int = 600
    # Where the rolling window is persisted (relative to the worker's cwd).
    scrape_state_dir: str = "_state"

    # --- Manual login / challenge handling ---
    # Login is done BY HAND in the browser window: no credentials are typed by
    # the app. Headless therefore cannot work — nobody is there to sign in.
    scrape_headless: bool = False
    # How long to hold the window open waiting for you to finish signing in.
    scrape_login_timeout_s: int = 600
    # How long to wait for you to clear a CAPTCHA / security checkpoint.
    scrape_challenge_timeout_s: int = 300

    # --- Human behaviour emulation ---
    # Bezier mouse paths, inertial scrolling, log-normal pacing, typo-correcting
    # typing, fingerprint consistency, honeypot avoidance. Off makes runs faster
    # and much more obviously automated; only useful for debugging selectors.
    scrape_humanize: bool = True
    # Browser fingerprint + anti-automation patching. Separate from humanize
    # because it is the layer most likely to *cause* trouble: reCAPTCHA and
    # similar fingerprint aggressively, and patched values that do not agree
    # can fail their check — producing a sign-in that loops after the CAPTCHA
    # rather than completing. Turn off to test whether that is happening.
    scrape_stealth: bool = True
    # Park the browser window off-screen for the parts of a run nobody needs to
    # watch, bringing it back only for sign-in and CAPTCHAs. Recruiters share
    # their machine with this, and a window that steals focus every few minutes
    # makes it unusable.
    #
    # Set false if searches stall on half-drawn pages. Minimising the window
    # provably does that — Chromium stops compositing and LinkedIn's lazily
    # drawn results never render past their skeleton placeholders — and while
    # off-screen keeps the window in its normal state and should paint, that is
    # not proven against LinkedIn itself. This switch is the way back.
    scrape_window_hidden: bool = True
    # Seeds the behaviour RNG for reproducible runs. Empty = fresh randomness.
    scrape_behavior_seed: str = ""
    # Max screenfuls to read down a profile while waiting for its lazy sections
    # (Experience/Skills render only once scrolled near, below the Activity
    # feed). Stops early once they appear or the page stops growing.
    scrape_max_profile_scrolls: int = 25
    # Follow "Show all" to the skills details page. The profile card lists
    # only the top two, and skills are 30% of the match score.
    scrape_fetch_all_skills: bool = True
    # IANA timezone reported to the page (e.g. "Africa/Cairo"). Empty keeps the
    # host's own timezone, which is the consistent choice when you log in
    # yourself from this machine.
    scrape_timezone: str = ""
    scrape_locale: str = "en-US"
    # How long a single page navigation may take. Playwright defaults to 30s,
    # which LinkedIn exceeds often enough to abort otherwise-healthy runs —
    # their pages are heavy and we deliberately arrive at a human pace.
    scrape_navigation_timeout_s: int = 60

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

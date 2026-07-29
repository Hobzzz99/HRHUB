"""Provider selection.

Callers ask for a provider by name and never branch on concrete type. Adding a
new source (LinkedIn Talent Solutions, an ATS, …) means adding a branch here and
a class — nothing else in the app changes.

Names map to *how* candidates are obtained:
  mock       — fixtures, no network
  linkedin   — scraping LinkedIn ourselves with Playwright, signed in by hand
               and capped at 20 profiles/hour (ToS-breaching, and liable to get
               the account restricted; see COMPLIANCE.md)
  apify      — LinkedIn data bought from Apify Actors (no LinkedIn account).
               Currently unused; needs APIFY_TOKEN to be set again.
"""

from __future__ import annotations

from app.core.config import settings
from app.providers.base import CandidateProvider
from app.providers.mock import MockProvider


def get_provider(name: str | None = None, **kwargs) -> CandidateProvider:
    """Return a provider instance for ``name`` (defaults to the configured one)."""
    provider_name = (name or settings.provider).lower()

    if provider_name == "mock":
        return MockProvider()

    if provider_name == "apify":
        # Lazily imported to match the playwright branch: a missing/blank Apify
        # token must not break the default mock path at import time.
        from app.providers.apify_linkedin import ApifyLinkedInProvider

        return ApifyLinkedInProvider(**kwargs)

    if provider_name in ("playwright", "linkedin"):
        # Imported lazily so the API image needn't carry Playwright, and so a
        # misconfigured scraping setup can't break the default mock path.
        # "linkedin" is the user-facing name; "playwright" names the mechanism.
        from app.providers.playwright_linkedin import PlaywrightLinkedInProvider

        return PlaywrightLinkedInProvider(**kwargs)

    raise ValueError(f"Unknown provider: {provider_name!r}")

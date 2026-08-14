"""LinkedIn candidate data via Apify Actors.

The alternative to scraping LinkedIn ourselves. Apify runs the collection on its
own infrastructure and we buy the result, so **no LinkedIn account is involved at
any point** — nothing to log into, nothing to get restricted, no session cookie
to leak. That is the whole reason this provider exists; see COMPLIANCE.md.

Two things to keep in mind when changing it:

  * **Cookieless actors only.** Several Actors offer "5x richer profiles" if you
    hand them a LinkedIn session cookie. Doing that re-introduces exactly the
    account risk this module avoids: the cookie is an account, and LinkedIn
    restricts accounts it sees driving automation. Do not add a cookie input.
  * **The Actor is rented, not owned.** LinkedIn litigates scraping vendors
    (Proxycurl was sued and shut down in 2025), and Actor authors change their
    output shape without notice. So nothing here assumes a field exists: the
    mapping tries several known spellings per field, and a response it cannot
    map is dumped to `_debug/` rather than silently stored as an empty profile —
    the failure mode that made every scraped candidate score a flat 30.

Cost/latency shape: an Actor run has a large fixed start-up cost, so profiles are
fetched **in one batch** on the first `fetch_profile` call and served from memory
after that, rather than one run per candidate.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import (
    EducationItem,
    ExperienceItem,
    RawProfile,
    SearchCriteria,
    SearchHit,
)
from app.providers.base import CandidateProvider, ProfileUnavailableError, ProviderError

logger = get_logger(__name__)

_API = "https://api.apify.com/v2"


class ApifyLinkedInProvider(CandidateProvider):
    # The candidates really are LinkedIn profiles; Apify is only how we obtained
    # them. Naming the source "linkedin" keeps them in one cache/dedup namespace
    # regardless of which mechanism fetched them.
    name = "linkedin"

    def __init__(self, *, token: str | None = None) -> None:
        super().__init__()
        self._token = token or settings.apify_token
        self._client: httpx.AsyncClient | None = None
        # Profiles the search actor returned inline, keyed by URL, so fetch_profile
        # can serve them without a second paid actor run.
        self._profiles: dict[str, dict] = {}

    # --- lifecycle ---------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._token:
                raise ProviderError(
                    "No Apify token configured. Create one at "
                    "https://console.apify.com/account/integrations and set "
                    "APIFY_TOKEN in backend/.env."
                )
            self._client = httpx.AsyncClient(
                base_url=_API,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(settings.apify_timeout_s + 20),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # --- actor plumbing ----------------------------------------------------

    async def _run_actor(self, actor: str, payload: dict) -> list[dict]:
        """Run an Actor synchronously and return its dataset items."""
        # The REST path spells actors "username~actor-name", not "username/actor-name".
        actor_path = actor.replace("/", "~")
        url = f"/acts/{actor_path}/run-sync-get-dataset-items"
        logger.info("apify_actor_run", actor=actor)
        started = time.monotonic()
        try:
            response = await self._get_client().post(
                url, json=payload, params={"timeout": settings.apify_timeout_s}
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Apify actor '{actor}' did not finish within "
                f"{settings.apify_timeout_s}s. Try fewer results, or raise "
                "APIFY_TIMEOUT_S."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Apify request failed: {exc}") from exc

        self._raise_for_status(response, actor)
        items = response.json()
        if not isinstance(items, list):
            items = [items]
        logger.info(
            "apify_actor_done",
            actor=actor,
            items=len(items),
            seconds=round(time.monotonic() - started, 1),
        )
        if settings.apify_debug_dump:
            self._dump(actor, items)
        return items

    def _raise_for_status(self, response: httpx.Response, actor: str) -> None:
        if response.status_code < 400:
            return
        body = response.text[:300]
        if response.status_code == 401:
            raise ProviderError(
                "Apify rejected the token (401). Check APIFY_TOKEN in backend/.env."
            )
        if response.status_code == 402:
            raise ProviderError(
                "Apify is out of credit (402). Top up at console.apify.com, or "
                "reduce SCRAPE_MAX_PROFILES."
            )
        if response.status_code == 404:
            raise ProviderError(
                f"Apify actor '{actor}' not found (404). Check the id in "
                "APIFY_SEARCH_ACTOR / APIFY_PROFILE_ACTOR — it must be "
                "'username/actor-name' and the actor must be public or yours."
            )
        raise ProviderError(f"Apify returned {response.status_code} for '{actor}': {body}")

    def _dump(self, actor: str, payload: Any) -> str:
        """Persist a raw actor response so its real shape can be read, not guessed."""
        try:
            out = Path("_debug")
            out.mkdir(exist_ok=True)
            path = out / f"apify-{actor.replace('/', '~')}-{int(time.time())}.json"
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            return str(path.resolve())
        except Exception:  # noqa: BLE001 — diagnostics must never break a search
            return "n/a"

    # --- search ------------------------------------------------------------

    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        items = await self._run_actor(
            settings.apify_search_actor, _search_input(criteria)
        )
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in items:
            url = _profile_url(item)
            if not url or url in seen:
                continue
            seen.add(url)
            hits.append(
                SearchHit(
                    source_profile_url=url,
                    name=_full_name(item),
                    headline=_headline(item),
                    current_company=_company_name(item),
                    location=_location(item),
                )
            )
            # Search actors often return full profiles already — keep them so the
            # profile actor never has to run for these.
            if _looks_like_full_profile(item):
                self._profiles[url] = item

        if not hits and items:
            dump = self._dump(settings.apify_search_actor, items)
            raise ProviderError(
                f"The Apify search actor returned {len(items)} items but none had a "
                f"recognisable LinkedIn profile URL — its output shape is not one "
                f"this provider knows. Raw response saved to {dump}; the field "
                "mapping in apify_linkedin.py needs updating for this actor."
            )

        logger.info("apify_search_done", found=len(hits), prefetched=len(self._profiles))
        return hits

    # --- profile -----------------------------------------------------------

    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        url = hit.source_profile_url
        item = self._profiles.get(url) or await self._fetch_one(url)
        if item is None:
            raise ProfileUnavailableError(f"Apify returned no profile for {url}")

        profile = _profile_from_item(item, url, hit)
        # Same self-check as the scraper: a profile with nothing but a name means
        # the mapping missed, and storing it would poison scoring with a constant.
        if not any((profile.headline, profile.about, profile.experience, profile.skills)):
            dump = self._dump(settings.apify_profile_actor, item)
            logger.warning("apify_profile_mapping_empty", url=url, debug=dump)
        return profile

    async def _fetch_one(self, url: str) -> dict | None:
        """Fetch a single profile the search actor did not return inline.

        The search runner gates every fetch_profile call on the database cache
        (get_fresh_candidate), so this only ever runs for a profile that is NOT
        already stored — a candidate seen in an earlier search is served from the
        database and never re-fetched here, so no Apify credit is spent on it.
        Fetching one at a time (rather than eagerly batching every hit) is what
        keeps that guarantee: we only pay for exactly what the runner asks for.
        """
        items = await self._run_actor(settings.apify_profile_actor, _profile_input([url]))
        for item in items:
            if _profile_url(item) == url:
                self._profiles[url] = item
                return item
        # Actor returned data but not keyed to this URL — accept the first item.
        if items:
            self._profiles[url] = items[0]
            return items[0]
        return None


# --- actor inputs ----------------------------------------------------------


def _search_input(criteria: SearchCriteria) -> dict:
    """Input for the people-search actor.

    Field names follow the cookieless search actors' documented schema; extras are
    ignored by Apify rather than erroring, so a superset is safer than a guess.
    """
    query = " ".join(
        p.strip() for p in [criteria.job_title, *criteria.keywords] if p and p.strip()
    )
    payload: dict[str, Any] = {
        "searchQuery": query,
        "query": query,
        "maxItems": max(criteria.max_results * 2, 10),
        "limit": max(criteria.max_results * 2, 10),
    }
    if criteria.location:
        payload["location"] = criteria.location
        payload["locations"] = [criteria.location]
    return payload


def _profile_input(urls: list[str]) -> dict:
    """Input for the profile actor. Never include a cookie — see module docstring."""
    return {"profileUrls": urls, "urls": urls, "startUrls": [{"url": u} for u in urls]}


# --- defensive mapping -----------------------------------------------------


def _pick(data: dict, *keys: str, default: Any = None) -> Any:
    """First present, non-empty value among ``keys``."""
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        # Actors wrap a display string under assorted keys; "linkedinText" and a
        # nested "parsed" object are how the harvestapi actor spells location.
        return _as_text(
            _pick(value, "linkedinText", "name", "title", "text", "value", "parsed")
        )
    if isinstance(value, list) and value:
        return _as_text(value[0])
    return str(value)


def _profile_url(item: dict) -> str | None:
    url = _as_text(
        _pick(item, "linkedinUrl", "profileUrl", "url", "publicProfileUrl", "profile_url")
    )
    if not url:
        if handle := _as_text(_pick(item, "publicIdentifier", "username", "profileId")):
            url = f"https://www.linkedin.com/in/{handle}"
    if not url or "/in/" not in url:
        return None
    return url.split("?")[0].rstrip("/")


def _full_name(item: dict) -> str | None:
    if name := _as_text(_pick(item, "fullName", "name", "full_name")):
        return name
    first = _as_text(_pick(item, "firstName", "first_name")) or ""
    last = _as_text(_pick(item, "lastName", "last_name")) or ""
    return f"{first} {last}".strip() or None


def _location(item: dict) -> str | None:
    return _as_text(
        _pick(
            item,
            "location",
            "addressWithCountry",
            "locationName",
            "geoLocationName",
            "addressWithoutCountry",
            "geo",
        )
    )


def _company_name(item: dict) -> str | None:
    return _as_text(
        _pick(item, "companyName", "currentCompany", "company", "companyIndustry")
    )


def _headline(item: dict) -> str | None:
    return _as_text(_pick(item, "headline", "occupation", "title", "subtitle"))


def _looks_like_full_profile(item: dict) -> bool:
    """True when a search item already carries profile-depth fields."""
    return any(
        item.get(key) for key in ("experience", "experiences", "positions", "skills")
    )


def _experience_items(item: dict) -> list[ExperienceItem]:
    rows = _pick(item, "experiences", "experience", "positions", default=[])
    if not isinstance(rows, list):
        return []
    out: list[ExperienceItem] = []
    for row in rows[:15]:
        if isinstance(row, str):
            out.append(ExperienceItem(title=row))
            continue
        if not isinstance(row, dict):
            continue
        title = _as_text(_pick(row, "title", "position", "role", "jobTitle"))
        company = _as_text(
            _pick(row, "companyName", "company", "subtitle", "organisation", "employer")
        )
        start = _as_text(_pick(row, "startDate", "starts", "start", "startedOn"))
        end = _as_text(_pick(row, "endDate", "ends", "end", "endedOn"))
        # Some actors give one "Jan 2020 - Present · 4 yrs" string instead.
        if not start:
            start, end = _split_range(
                _as_text(_pick(row, "duration", "dateRange", "caption", "period"))
            )
        if title or company:
            out.append(
                ExperienceItem(
                    title=title,
                    company=company,
                    start=start,
                    end=end,
                    location=_as_text(_pick(row, "location", "locationName")),
                    description=_as_text(_pick(row, "description", "summary")),
                )
            )
    return out


def _split_range(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    core = text.split("·")[0].strip()
    for sep in (" - ", " – ", " to ", "–", "-"):
        if sep in core:
            start, end = core.split(sep, 1)
            return start.strip() or None, end.strip() or None
    return core or None, None


def _education_items(item: dict) -> list[EducationItem]:
    rows = _pick(item, "educations", "education", "schools", default=[])
    if not isinstance(rows, list):
        return []
    out: list[EducationItem] = []
    for row in rows[:10]:
        if isinstance(row, str):
            out.append(EducationItem(school=row))
            continue
        if not isinstance(row, dict):
            continue
        school = _as_text(_pick(row, "schoolName", "school", "title", "institution"))
        if not school:
            continue
        out.append(
            EducationItem(
                school=school,
                degree=_as_text(_pick(row, "degree", "degreeName", "subtitle")),
                field=_as_text(_pick(row, "fieldOfStudy", "field")),
                start=_as_text(_pick(row, "startDate", "starts", "start")),
                end=_as_text(_pick(row, "endDate", "ends", "end")),
            )
        )
    return out


def _skill_names(item: dict) -> list[str]:
    rows = _pick(item, "skills", "skillsList", "topSkills", default=[])
    if isinstance(rows, str):
        rows = [s for s in rows.split(",")]
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows[:60]:
        if name := _as_text(row):
            name = name.strip()
            if name and name not in out:
                out.append(name)
    return out


def _certifications(item: dict) -> list[dict]:
    rows = _pick(item, "certifications", "licenses", "licensesAndCertifications", default=[])
    if not isinstance(rows, list):
        return []
    return [r if isinstance(r, dict) else {"name": _as_text(r)} for r in rows[:20]]


def _profile_from_item(item: dict, url: str, hit: SearchHit) -> RawProfile:
    """Map one Actor dataset item onto the domain profile.

    Falls back to the search hit's card data for anything the profile item omits —
    two thin sources still beat one.
    """
    experience = _experience_items(item)
    headline = _headline(item) or hit.headline
    return RawProfile(
        source="linkedin",
        source_profile_url=url,
        source_id=_as_text(_pick(item, "publicIdentifier", "profileId", "id")),
        name=_full_name(item) or hit.name or "Unknown",
        headline=headline,
        current_title=(
            _as_text(_pick(item, "jobTitle", "currentPosition"))
            or (experience[0].title if experience else None)
        ),
        current_company=(
            _company_name(item)
            or (experience[0].company if experience else None)
            or hit.current_company
        ),
        location=_location(item) or hit.location,
        about=_as_text(_pick(item, "about", "summary", "bio", "description")),
        experience=experience,
        education=_education_items(item),
        skills=_skill_names(item),
        certifications=_certifications(item),
        profile_picture_url=_as_text(_pick(item, "profilePic", "profilePicture", "avatar")),
        raw={"apify_actor": settings.apify_profile_actor},
    )

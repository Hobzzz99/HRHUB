"""Drive LinkedIn's own people filters, and keep the ids they resolve.

The search box takes the **job title and nothing else** — the way a recruiter
uses it. Everything that narrows the result set (employer, location) is applied
through LinkedIn's filter panel afterwards, because those are real facets:
LinkedIn resolves them to ids and filters server-side.

Folding them into the search text instead is worse twice over. It is imprecise —
"external audit manager Egypt" matches anyone who merely mentions Egypt — and it
does not actually restrict anything, so profiles we would discard still cost
hourly budget to open.

LinkedIn filters employers by numeric company id, not by text — its people
search carries ``currentCompany=["9499295","1073","1038"]``. Applying that facet
is worth real money here: it filters **server-side**, so people at other firms
never become a profile we open, and the hourly scrape budget is spent only on
candidates who already qualify.

There is no public name→id lookup, and hard-coding a table would be guesswork
that silently filters to the wrong employer — an id belongs to a specific legal
entity, so "KPMG" and "KPMG Middle East" are different pages with different ids.
So ids are obtained the way a person gets them: open the filter panel, tick or
search for each firm, apply, and read the ids back out of the URL LinkedIn then
navigates to. Every id found is **cached to disk**, so a firm is driven through
the UI once and every later search goes straight to a URL.

Selectors here anchor on visible text and aria labels only. LinkedIn's class
names are build-hashed and rotate on every deploy, so anything keyed on them
would break within days.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, unquote, urlparse

from playwright.async_api import Page

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.human import HumanActor

logger = get_logger(__name__)

#: A facet is the same interaction every time — open the pill, tick or search
#: for each value, apply — so the two we drive differ only in their labels and
#: the URL parameter LinkedIn writes the resolved ids into.
class Facet(NamedTuple):
    name: str
    pill: tuple[str, ...]
    add: tuple[str, ...]
    typeahead: tuple[str, ...]
    url_param: str


COMPANY = Facet(
    name="company",
    # The pill is a **div with role="button"**, not a <button>. Selectors that
    # named the tag matched nothing on a fully rendered page — the bar was
    # there, we simply could not see it — so every search fell back to
    # unfiltered results and the Big Four constraint never reached LinkedIn.
    # Its own markup is:
    #   <div role="button" aria-label="Filter by Current companies">
    #     <label>Current companies …</label>
    # Plural: LinkedIn labels it "Current companies" and adds a count badge.
    pill=(
        '[aria-label*="Current compan" i]',
        '[role="button"]:has-text("Current companies")',
        '[role="button"]:has-text("Current company")',
        'button:has-text("Current companies")',
    ),
    add=(
        'button:has-text("Add a company")',
        '[role="button"]:has-text("Add a company")',
    ),
    typeahead=(
        'input[placeholder*="Add a company" i]',
        'input[aria-label*="Add a company" i]',
    ),
    url_param="currentCompany",
)

LOCATION = Facet(
    name="location",
    # Same shape as COMPANY: a div with role="button", not a <button>.
    pill=(
        '[aria-label*="Filter by Location" i]',
        '[role="button"]:has-text("Locations")',
        '[role="button"]:has-text("Location")',
        'button:has-text("Locations")',
    ),
    add=(
        'button:has-text("Add a location")',
        '[role="button"]:has-text("Add a location")',
    ),
    typeahead=(
        'input[placeholder*="Add a location" i]',
        'input[aria-label*="Add a location" i]',
    ),
    #: LinkedIn resolves a place to a geo urn, not a company id.
    url_param="geoUrn",
)

_TYPEAHEAD_FALLBACK = ('div[role="dialog"] input[role="combobox"]',)
_OPTION = ('[role="option"]',)
#: The panel's confirm button. Its label sits in a `<span>` inside a
#: `div[role="button"]`, so a selector naming the `button` tag matches nothing —
#: the same fault that stopped the pill itself being found. Role-based first,
#: tag-based kept last as a fallback if LinkedIn ever ships real buttons.
_APPLY = (
    '[role="button"]:has-text("Show results")',
    '[aria-label*="Apply current filter" i]',
    'button:has-text("Show results")',
)
_ID_DIGITS = re.compile(r"\d+")


def ids_in_url(url: str, param: str = "currentCompany") -> list[str]:
    """Every id a LinkedIn people-search URL carries for ``param``.

    Handles the encodings LinkedIn actually emits — ``%5B"123"%2C"456"%5D`` and
    the plain ``["123","456"]`` you get by copying the address bar.
    """
    raw = parse_qs(urlparse(url).query).get(param)
    if not raw:
        return []
    decoded = unquote(raw[0])
    try:
        parsed = json.loads(decoded)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).isdigit()]
    except ValueError:
        pass
    return _ID_DIGITS.findall(decoded)


class CompanyIdCache:
    """Name → LinkedIn company id, persisted so a firm is resolved once."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(
            path or Path(settings.scrape_state_dir) / "linkedin_company_ids.json"
        )

    @staticmethod
    def _key(name: str) -> str:
        return " ".join(name.lower().split())

    def _load(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def get(self, name: str) -> str | None:
        return self._load().get(self._key(name))

    def known(
        self, names: list[str], facet: str = "company"
    ) -> tuple[list[str], list[str]]:
        """Split ``names`` into (ids already cached, names still to resolve)."""
        cached = self._load()
        ids: list[str] = []
        missing: list[str] = []
        for name in names:
            if not name or not name.strip():
                continue
            found = cached.get(self._key(f"{facet}:{name}"))
            (ids.append(found) if found else missing.append(name))
        return ids, missing

    def put(self, name: str, company_id: str) -> None:
        cached = self._load()
        cached[self._key(name)] = company_id
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-replace: a crash mid-write must not leave a truncated
            # file, which would read back empty and re-drive the whole UI.
            temp = self._path.with_suffix(f".{os.getpid()}.tmp")
            temp.write_text(json.dumps(cached, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError:
            logger.warning("company_id_cache_write_failed", exc_info=True)


#: How long to wait for the filter bar before deciding it is not coming.
#: LinkedIn renders results and pagination first and the filter pills a beat
#: later, so a single immediate check found nothing on a page that was merely
#: still drawing — and the search then ran completely unfiltered.
PILL_WAIT_S = 20.0


async def _first_visible(page: Page, selectors: tuple[str, ...], *, timeout_s: float = 0.0):
    """The first of these selectors that is present and visible.

    Polls until ``timeout_s`` when given one, because the element may not have
    rendered yet. Zero means answer immediately — right for elements that only
    exist once a panel we just opened is on screen.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() > 0 and await locator.is_visible():
                    return locator
            except Exception:  # noqa: BLE001 — a stale selector is simply not this one
                continue
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.5)


def _label_pattern(name: str) -> re.Pattern[str]:
    """Match a firm's checkbox label without matching words that contain it.

    Word-bounded because short names are substrings of unrelated employers —
    a bare "EY" would otherwise tick "Honeywell" or "Key Bank". Anchored at the
    start so "KPMG" still ticks "KPMG Middle East", which is the entity a
    regional search actually wants.
    """
    return re.compile(rf"^\s*{re.escape(name.strip())}\b", re.I)


async def _select_one(
    page: Page, actor: HumanActor, facet: Facet, name: str
) -> bool:
    """Tick ``name`` in the open filter panel, via checkbox or typeahead."""
    # LinkedIn pre-offers recent and suggested values as checkboxes; ticking one
    # is cheaper and more ordinary-looking than typing.
    checkbox = page.get_by_label(_label_pattern(name)).first
    try:
        if await checkbox.count() > 0:
            await checkbox.scroll_into_view_if_needed(timeout=3000)
            if await checkbox.is_visible():
                await actor.click(checkbox)
                await actor.dwell(0.5)
                logger.info("facet_ticked_from_list", facet=facet.name, value=name)
                return True
    except Exception:  # noqa: BLE001 — fall through to the typeahead
        pass

    add = await _first_visible(page, facet.add)
    if add is not None:
        await actor.click(add)
        await actor.dwell(0.6)

    field = await _first_visible(page, facet.typeahead + _TYPEAHEAD_FALLBACK)
    if field is None:
        logger.info("facet_typeahead_missing", facet=facet.name, value=name)
        return False

    await actor.type_into(field, name)
    # The typeahead is a network round-trip; let the options render.
    await actor.dwell(1.6)

    option = await _first_visible(page, _OPTION)
    if option is None:
        logger.info("facet_no_match", facet=facet.name, value=name)
        return False

    await actor.click(option)
    await actor.dwell(0.6)
    return True


async def apply_facet(
    page: Page,
    actor: HumanActor,
    facet: Facet,
    values: list[str],
    cache: CompanyIdCache | None = None,
) -> list[str]:
    """Select every value in ``values`` and return the ids LinkedIn resolved.

    All values are selected in **one** visit to the panel, which is faster and
    closer to how a person uses it than opening it once each. Returns ``[]``
    when the panel cannot be driven, so the caller can fall back.
    """
    pill = await _first_visible(page, facet.pill, timeout_s=PILL_WAIT_S)
    if pill is None:
        logger.info("facet_pill_not_found", facet=facet.name, waited_s=PILL_WAIT_S)
        return []

    await actor.click(pill)
    await actor.dwell(1.0)

    selected = [
        value for value in values if await _select_one(page, actor, facet, value)
    ]
    if not selected:
        return []

    apply_button = await _first_visible(page, _APPLY)
    if apply_button is not None:
        await actor.click(apply_button)

    # Applying rewrites the URL with the facet. Wait for that rather than a
    # fixed pause, so a slow response is not mistaken for a failed filter.
    try:
        await page.wait_for_url("**currentCompany**", timeout=15000)
    except Exception:  # noqa: BLE001 — checked properly on the next line
        logger.info("company_filter_url_never_updated", url=page.url[:200])

    ids = ids_in_url(page.url, facet.url_param)
    if not ids:
        logger.info("facet_no_ids_in_url", facet=facet.name, url=page.url[:200])
        return []

    # The URL gives ids but not which value each belongs to. Only record the
    # mapping when it is unambiguous — one requested, one returned. Guessing the
    # pairing would cache a value under the wrong id and silently filter every
    # future search to the wrong employer or the wrong city.
    if cache is not None and len(selected) == 1 and len(ids) == 1:
        cache.put(f"{facet.name}:{selected[0]}", ids[0])

    logger.info("facet_applied", facet=facet.name, selected=len(selected), ids=len(ids))
    return ids


async def apply_company_filter(
    page: Page, actor: HumanActor, names: list[str], cache: CompanyIdCache
) -> list[str]:
    """Restrict results to the given employers."""
    return await apply_facet(page, actor, COMPANY, names, cache)


async def apply_location_filter(
    page: Page, actor: HumanActor, places: list[str], cache: CompanyIdCache | None = None
) -> list[str]:
    """Restrict results to the given places.

    Worth applying rather than putting the place in the search text: LinkedIn
    resolves it to a geo id and filters server-side, so people elsewhere never
    become a profile we open.
    """
    return await apply_facet(page, actor, LOCATION, places, cache)


def company_ids_in_url(url: str) -> list[str]:
    """Backwards-compatible alias for the company facet."""
    return ids_in_url(url, COMPANY.url_param)

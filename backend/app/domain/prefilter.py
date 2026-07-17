"""Conservative pre-filter applied to search-result cards.

Runs before opening full profiles, to cut page loads and rate-limit exposure.
Because search cards expose only shallow data, this discards **only clear
mismatches** — never a borderline case — so a strong candidate whose headline
undersells them is still opened and scored.
"""

from __future__ import annotations

import re

from app.domain.models import SearchCriteria, SearchHit

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def passes_prefilter(hit: SearchHit, criteria: SearchCriteria) -> tuple[bool, str | None]:
    """Return ``(keep, discard_reason)``.

    Only two hard, high-confidence signals discard a card:
      * an explicit location requirement that the card's stated location clearly
        contradicts (and neither side is remote), and
      * an explicit company requirement the card's company clearly contradicts.
    Everything else is kept for full scoring.
    """
    # Location: only when required, both present, no shared token, neither remote.
    if criteria.enforce_location and criteria.location and hit.location:
        req = _tokens(criteria.location)
        loc = _tokens(hit.location)
        remote = "remote" in req or "remote" in loc
        if not remote and req and loc and not (req & loc):
            return False, f"Location '{hit.location}' does not match '{criteria.location}'"

    # Company: only when required and both present with no overlap.
    if criteria.company and hit.current_company:
        want = _tokens(criteria.company)
        have = _tokens(hit.current_company)
        if want and have and not (want & have):
            return False, (
                f"Company '{hit.current_company}' does not match '{criteria.company}'"
            )

    return True, None

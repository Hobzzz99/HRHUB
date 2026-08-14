"""Employer matching, used as the fallback when LinkedIn's own filter is unavailable.

The precise path is LinkedIn's `currentCompany` search facet, which filters
server-side and therefore never spends scrape budget on people who do not work
there. When that cannot be applied, these helpers filter the result cards
locally on the company name each card already shows — still before any profile
is opened, so it costs nothing either, just less reliably.

Name matching needs help: a card reading "Ernst & Young" must satisfy a search
for "EY", and "PwC" must satisfy "PricewaterhouseCoopers". The alias table below
is deliberately small and covers the firms recruiters actually search by name.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Words that appear in company names without identifying them.
_NOISE = frozenset(
    {
        "the", "and", "of", "group", "global", "international", "worldwide",
        "llp", "llc", "ltd", "limited", "inc", "incorporated", "plc", "gmbh",
        "co", "company", "corp", "corporation", "holdings", "partners",
        "consulting", "services", "solutions", "middle", "east",
    }
)

#: Each entry maps a firm to the distinctive tokens any of its names contain.
#: A card matches if it carries **any** of them, which is what lets "EY" find
#: "Ernst & Young LLP" and "Deloitte" find "Deloitte & Touche".
_ALIASES: dict[str, frozenset[str]] = {
    "deloitte": frozenset({"deloitte", "touche"}),
    "pwc": frozenset({"pwc", "pricewaterhousecoopers", "pricewaterhouse"}),
    "ey": frozenset({"ey", "ernst"}),
    "kpmg": frozenset({"kpmg"}),
    "bdo": frozenset({"bdo"}),
    "grantthornton": frozenset({"grant", "thornton"}),
}

#: The four firms recruiters ask for as a set. Exposed so the UI and the API
#: agree on what "Big Four" means rather than each hard-coding a list.
BIG_FOUR = ("Deloitte", "PwC", "EY", "KPMG")


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _NOISE}


def _identifying_tokens(name: str) -> frozenset[str]:
    """The tokens that would identify ``name`` on a profile card."""
    tokens = _tokens(name)
    for alias_tokens in _ALIASES.values():
        if tokens & alias_tokens:
            return alias_tokens
    return frozenset(tokens)


def matches(
    requested: list[str],
    candidate_company: str | None,
    *,
    allow_unknown: bool = True,
) -> bool:
    """True when ``candidate_company`` looks like one of ``requested``.

    An empty request matches everything: a filter nobody set must not exclude
    anyone.

    ``allow_unknown`` decides what an *absent* employer means, and the right
    answer differs by stage. On a search card it is missing data — LinkedIn
    frequently omits it — and rejecting there would discard people who do work
    at the firm before we ever look. Once the full profile is open we know the
    employer, so an absent one can no longer be given the benefit of the doubt:
    "only show me people at the Big Four" has to mean exactly that.
    """
    if not requested:
        return True
    have = _tokens(candidate_company)
    if not have:
        return allow_unknown
    return any(_identifying_tokens(name) & have for name in requested if name.strip())


def current_employer(profile) -> str | None:
    """The employer to judge, falling back to the most recent role."""
    if profile.current_company:
        return profile.current_company
    for item in profile.experience:
        if item.company:
            return item.company
    return None

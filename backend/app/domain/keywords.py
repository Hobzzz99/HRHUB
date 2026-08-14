"""Keyword matching against a candidate's headline and job titles.

The 30% keyword component of the score. Deliberately scoped to the text where a
candidate *claims* something — headline, current title, the title of every
position held, and their certifications and licences — and not the long-form
About section or role descriptions. A term buried in a paragraph is weak
evidence; the same term in a title or a credential is a claim their employer and
network can see, which is what keeps precision high.

Matching is token-based rather than substring, because substring matching fails
on exactly the cases recruiters care about: "vendor management" is not a
substring of "Senior Vendor Manager".
"""

from __future__ import annotations

import re

from app.domain.models import RawProfile

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Seniority and filler that appear in almost every title. Ignored so a keyword
#: is judged on the role itself, not on words that carry no matching signal.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "and", "or", "for", "with", "at", "in", "to",
        "senior", "junior", "lead", "head", "chief", "principal", "staff",
    }
)

#: Two tokens with a shared prefix this long are treated as the same word.
#: Chosen so "manager"/"management" (shares "manage") and
#: "engineer"/"engineering" both match, while "data"/"database" do not.
_MIN_SHARED_PREFIX = 5


def _normalize(token: str) -> str:
    """Fold a token's plural form. ``vendors`` and ``vendor`` must compare equal."""
    if len(token) >= 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str | None, *, keep_stopwords: bool = False) -> set[str]:
    if not text:
        return set()
    found = (_normalize(t) for t in _TOKEN_RE.findall(text.lower()))
    if keep_stopwords:
        return set(found)
    return {t for t in found if t not in _STOPWORDS}


def _shared_prefix_len(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def _token_matches(required: str, available: set[str]) -> bool:
    """True when ``required`` appears in ``available``, allowing word-form drift.

    Exact first, then a shared-prefix fallback so "manager" satisfies a search
    for "management". The fallback accepts some over-matching — "product" also
    satisfies "production" — which is the right trade for recruiting, where a
    missed candidate is invisible and a loose one is merely skimmed past.
    """
    if required in available:
        return True
    return any(
        _shared_prefix_len(required, candidate) >= _MIN_SHARED_PREFIX
        for candidate in available
    )


#: Keys a provider might use for the name of a certification or licence.
_CREDENTIAL_NAME_KEYS = ("name", "title", "authority")


def _credential_names(entries: list[dict]) -> list[str]:
    names: list[str] = []
    for entry in entries:
        for key in _CREDENTIAL_NAME_KEYS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value)
                break
    return names


def searchable_fields(profile: RawProfile) -> list[str]:
    """Every place a candidate *claims* something, kept as separate fields.

    The dividing line is structure, not location. Included are the short,
    declared fields a candidate fills in deliberately and that others can check:
    the display name, headline, current title, the title of every role, listed
    skills, certifications and licences. A term like "CPA" lives in whichever of
    those a given person happened to use, so searching only one of them makes the
    match depend on profile-keeping habits rather than on the person.

    The **name** is in that list for a reason specific to this market: finance
    and audit professionals routinely append their credential to it — "Walid Gad,
    CPA, CMA". Leaving it out discarded 4 of the 11 CPAs on a Big Four audit
    shortlist, and 11 of 42 across the whole archive, every one of them an
    "Audit Manager, CPA" whose only sin was writing it where LinkedIn shows it
    most. A credential appended to a name is the same kind of deliberate,
    checkable claim as one in the headline.

    Still deliberately excluded: the About section and role descriptions. Those
    are prose, where a term is weak evidence — people write "exposure to
    procurement" about a single project.

    Returned as a **list, not one joined string**, because a multi-word keyword
    must be satisfied inside a single field. Flattening them lets an unrelated
    skill donate a word to a job title: an *Internal* Audit Manager who lists
    "External Reporting" would otherwise satisfy "external audit manager".
    """
    fields: list[str] = [
        profile.name or "",
        profile.headline or "",
        profile.current_title or "",
    ]
    fields.extend(item.title or "" for item in profile.experience)
    fields.extend(profile.skills)
    fields.extend(_credential_names(profile.certifications))
    fields.extend(_credential_names(profile.licenses))
    return [field for field in fields if field and field.strip()]


class KeywordMatch:
    """Which of the requested keywords the candidate's titles support."""

    __slots__ = ("matched", "missing")

    def __init__(self, matched: list[str], missing: list[str]) -> None:
        self.matched = matched
        self.missing = missing

    @property
    def ratio(self) -> float:
        """Fraction matched. 1.0 when nothing was asked for — an unstated
        requirement must not penalise anyone."""
        total = len(self.matched) + len(self.missing)
        return 1.0 if total == 0 else len(self.matched) / total


def match_keywords(required: list[str], searchable: str | list[str]) -> KeywordMatch:
    """Match each requested keyword against one or more searchable fields.

    A multi-word keyword matches only when **every** one of its meaningful
    tokens is present **in the same field** — so "external audit manager" is
    satisfied by the title *External Audit Manager*, but not by an *Internal*
    Audit Manager who separately lists an "External Reporting" skill. Original
    spelling is preserved in the result so the UI reads back what was typed.
    """
    fields = [searchable] if isinstance(searchable, str) else searchable
    per_field_tokens = [_tokens(field) for field in fields]
    matched: list[str] = []
    missing: list[str] = []

    for term in required:
        if not term or not term.strip():
            continue
        wanted = _tokens(term)
        if not wanted:
            # Keyword was entirely stopwords ("senior"); nothing to test against.
            wanted = _tokens(term, keep_stopwords=True)
        found = bool(wanted) and any(
            all(_token_matches(token, available) for token in wanted)
            for available in per_field_tokens
        )
        (matched if found else missing).append(term.strip())

    return KeywordMatch(matched=matched, missing=missing)


def match_keywords_in_profile(required: list[str], profile: RawProfile) -> KeywordMatch:
    """`match_keywords` against everything the candidate claims — see `searchable_fields`."""
    return match_keywords(required, searchable_fields(profile))

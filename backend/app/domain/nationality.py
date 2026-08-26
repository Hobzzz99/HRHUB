"""Judging likely nationality from where somebody studied.

LinkedIn has no nationality field, so this cannot be filtered the way an employer
or a location can. What a profile does carry is **where the person went to
university**, self-declared and checkable, and for a country whose graduates
overwhelmingly hold its citizenship that is real evidence.

Two things this deliberately does not do:

* **It never infers nationality from a name.** Name-based inference is
  unreliable in both directions and, in recruiting, is the textbook route to a
  discrimination claim.
* **It does not treat working in a country as evidence of being from it.** That
  is the exact distinction the recruiter is drawing. Audit practices in the Gulf
  are staffed heavily by expatriates, so "twelve years at PwC Riyadh" says
  nothing about citizenship — it is the signal most likely to be mistaken for
  one.

The result is a *likelihood with its evidence attached*, not a verdict. A
recruiter can see "studied at King Saud University" and judge it; they cannot
judge a silent yes/no, and neither should be presented as fact.

Nationality-based hiring criteria are lawful in some places and not in others.
Inside Saudi Arabia, Saudization (Nitaqat) makes citizenship a legitimate and
routine requirement; the same filter applied elsewhere may not be. That is the
employer's call to make knowingly, which is another reason the evidence is shown
rather than hidden behind a checkbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Distinctive fragments of the institution names for each country. Matched on
#: the school as the candidate wrote it, so several spellings of the same
#: university all land.
_INSTITUTIONS: dict[str, frozenset[str]] = {
    "saudi arabia": frozenset(
        {
            # National universities, by the fragment that identifies them.
            "king saud", "king abdulaziz", "king abdul aziz", "kau", "ksu",
            "king fahd university", "kfupm", "king khalid university",
            "imam muhammad", "imam mohammad", "imam abdulrahman", "king faisal university",
            "umm al-qura", "umm al qura", "taibah", "qassim", "jazan", "jizan",
            "taif university", "hail university", "university of hail", "najran",
            "al jouf", "aljouf", "jouf university", "northern border",
            "princess nourah", "prince sultan university", "alfaisal", "al faisal university",
            "dar al uloom", "effat", "prince mohammad bin fahd", "pmu",
            "saudi electronic university", "shaqra", "majmaah",
            "prince sattam", "university of dammam", "king saud bin abdulaziz",
            "yanbu university", "jubail university", "batterjee",
            "arab open university saudi", "riyadh college", "king abdullah university",
        }
    ),
}

#: Institutions inside the country whose intake is largely international, so
#: attendance is weak evidence of citizenship rather than good evidence.
_INTERNATIONAL_INTAKE: dict[str, frozenset[str]] = {
    "saudi arabia": frozenset(
        {"king abdullah university", "islamic university of madinah", "kaust"}
    ),
}

#: How somebody states it themselves. Stronger than any inference, and people do
#: write it — usually *because* of the hiring rules that make it matter.
_SELF_DECLARED: dict[str, tuple[str, ...]] = {
    "saudi arabia": ("saudi national", "saudi citizen", "saudi nationality"),
}

#: Countries this module can actually assess. A request for anything else is
#: reported as unsupported rather than quietly matching nobody.
SUPPORTED = frozenset(_INSTITUTIONS)


@dataclass(slots=True)
class NationalitySignal:
    """A likelihood and the reasons for it. Never a claim of fact."""

    likely: bool
    evidence: list[str] = field(default_factory=list)
    #: True when the country cannot be assessed at all, which is a gap in this
    #: module rather than anything about the candidate.
    unsupported: bool = False
    #: True when the profile lists no education, so there is nothing to judge.
    #:
    #: This is the common case, not the edge case: education was readable on 102
    #: of 237 profiles in the real archive, and on none of the sixteen based in
    #: Saudi Arabia. Rejecting on it would discard well over half of every
    #: shortlist for a fact about extraction rather than about the person —
    #: which is the failure mode this project keeps having to design against.
    unknown: bool = False

    @property
    def contradicted(self) -> bool:
        """Education was readable and none of it was in the country."""
        return not self.likely and not self.unknown and not self.unsupported


def can_assess(country: str) -> bool:
    """Whether this country can be judged at all."""
    return _normalise(country) in SUPPORTED


def _normalise(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(_TOKEN_RE.findall(text.lower()))


def assess(profile, country: str) -> NationalitySignal:
    """How likely this person holds ``country``'s citizenship, and why."""
    key = _normalise(country)
    if key not in SUPPORTED:
        return NationalitySignal(likely=False, unsupported=True)

    evidence: list[str] = []

    declared = _normalise(f"{profile.headline or ''} {profile.about or ''}")
    for phrase in _SELF_DECLARED[key]:
        if phrase in declared:
            evidence.append(f'States "{phrase}" on their profile')
            break

    weak = _INTERNATIONAL_INTAKE.get(key, frozenset())
    for item in profile.education:
        school = _normalise(getattr(item, "school", None))
        if not school:
            continue
        for fragment in _INSTITUTIONS[key]:
            if fragment not in school:
                continue
            # Named so a recruiter can weigh it, and flagged when the institution
            # takes enough international students that it proves little.
            note = " (international intake — weak evidence)" if fragment in weak else ""
            evidence.append(f"Studied at {item.school}{note}")
            break

    strong = [e for e in evidence if "weak evidence" not in e]
    has_education = any(getattr(item, "school", None) for item in profile.education)
    return NationalitySignal(
        likely=bool(strong),
        evidence=evidence,
        unknown=not evidence and not has_education,
    )

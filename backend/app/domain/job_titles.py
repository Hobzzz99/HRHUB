"""Reading a job title the way a recruiter does: what the job is, and how senior.

A title carries two independent things. *"External Audit Manager"* is a job —
external audit — held at a level — manager. Scoring them together is what let a
**Finance Manager** score 33% against a search for *external audit manager*: the
only word they shared was "manager", which every management title contains and
which says nothing about what the person does.

So the two are separated. The **domain** decides whether this is even the right
job; the **seniority** decides whether it is the right level. A candidate who
matches only on seniority is not a partial match, they are a different job.

Domain is judged across the candidate's **whole career** — every job title they
have held, plus their headline and employers — not just their current title.
Someone titled "Audit Manager" whose history is audit roles at an audit firm is
an audit manager, whatever their current line reads.
"""

from __future__ import annotations

import re

from app.domain.keywords import _shared_prefix_len, _tokens
from app.domain.models import RawProfile

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Words that describe a *level*, not a job. Shared between almost every title
#: in a hierarchy, so they carry no signal about what someone actually does.
SENIORITY = frozenset(
    {
        "intern", "trainee", "junior", "associate", "assistant", "graduate",
        "senior", "snr", "sr", "mid", "lead", "leader", "principal", "staff",
        "supervisor", "manager", "management", "head", "deputy", "chief",
        "director", "vp", "president", "partner", "officer", "executive",
        "specialist", "consultant", "coordinator", "controller", "expert",
        "group", "global", "regional", "country",
    }
)

#: Rough ordering, so "senior manager" can satisfy a search for "manager" but a
#: "trainee" cannot. Titles absent from this map score as an unknown level,
#: which neither helps nor blocks.
_RANK = {
    "intern": 1, "trainee": 1, "graduate": 1,
    "junior": 2, "assistant": 2, "associate": 2,
    "mid": 3, "specialist": 3, "consultant": 3, "coordinator": 3,
    "senior": 4, "snr": 4, "sr": 4, "expert": 4,
    "lead": 5, "leader": 5, "principal": 5, "staff": 5, "supervisor": 5,
    "manager": 6, "management": 6, "controller": 6,
    "head": 7, "deputy": 7,
    "director": 8, "chief": 9, "vp": 9, "president": 9, "partner": 9,
}

#: How much of the title score seniority is worth. Domain is the larger share
#: because being in the wrong job disqualifies; being one level off does not.
_SENIORITY_WEIGHT = 0.30

#: Words that split a profession in two, mapped to the base work they qualify
#: and the word that contradicts them.
#:
#: These exist because a profession's *default* variant usually goes unnamed. At
#: an audit firm the statutory work is titled "Audit Manager" or "Audit &
#: Assurance Senior" — nobody writes "external", and demanding the literal word
#: discarded audit managers at all four of the Big Four. Internal auditors, by
#: contrast, say "internal" every time, because theirs is the variant that needs
#: distinguishing. So an unqualified audit role reads as external audit, while an
#: explicitly internal one never does.
_QUALIFIERS: dict[str, tuple[frozenset[str], str]] = {
    "external": (frozenset({"audit", "assurance"}), "internal"),
}


def split(title: str) -> tuple[set[str], set[str]]:
    """Split a title into (domain tokens, seniority tokens)."""
    tokens = _tokens(title)
    seniority = {t for t in tokens if t in SENIORITY}
    return tokens - seniority, seniority


def _stated(required: str, available: set[str]) -> bool:
    """Word-form-tolerant membership, as used for keywords.

    Lets "audit" be satisfied by "auditor" and "auditing", which is how the same
    job is written across a career.
    """
    if required in available:
        return True
    return any(_shared_prefix_len(required, other) >= 5 for other in available)


def _matches(required: str, available: set[str]) -> bool:
    """Whether a title word is evidenced, allowing for the unnamed default.

    A qualifier like "external" counts as met when the base work is present and
    nothing contradicts it — see ``_QUALIFIERS`` for why that is the recruiter's
    reading rather than a loosening of the check.
    """
    if _stated(required, available):
        return True
    qualifier = _QUALIFIERS.get(required)
    if qualifier is None:
        return False
    base_words, contradiction = qualifier
    if _stated(contradiction, available):
        return False
    return any(_stated(word, available) for word in base_words)


def career_evidence(profile: RawProfile) -> str:
    """Everywhere a candidate's line of work shows up over their whole history.

    Every job title held, the headline, and employers — an audit firm on the CV
    is itself evidence of audit work.

    Read as one pooled body of text, not role by role. Localising it per role
    was tried and is wrong here: nearly every internal auditor has one early
    role titled plainly "Auditor", which on its own reads as the unnamed default
    and let them back through the very check that is meant to separate the two
    professions. A qualifier has to be judged against the whole career.

    Deliberately **not** the About section, role descriptions, or the skills
    list. The first two are prose, and this feeds a disqualifying check. The
    skills list is excluded for a sharper reason: it is self-declared and costs
    nothing to add, so an "External Audit" tag was letting finance managers with
    no audit role in their history clear a search for external auditors. A title
    is a claim an employer and a network can see; a skill tag is not. Skills
    still count for keyword matching, where self-declaration is fair evidence.
    """
    parts: list[str] = [profile.headline or "", profile.current_title or ""]
    for item in profile.experience:
        parts.append(item.title or "")
        parts.append(item.company or "")
    return " ".join(p for p in parts if p)


def current_level_text(profile: RawProfile) -> str:
    """Where a candidate's *present* level is stated."""
    return " ".join(p for p in (profile.current_title or "", profile.headline or "") if p)


def domain_match(required_title: str, profile: RawProfile) -> float:
    """Fraction of the role's domain words evidenced anywhere in the career."""
    domain, _ = split(required_title)
    if not domain:
        return 1.0  # a title made only of seniority words asks nothing of the domain
    available = _tokens(career_evidence(profile))
    found = sum(1 for token in domain if _matches(token, available))
    return found / len(domain)


def seniority_match(required_title: str, profile: RawProfile) -> float:
    """How well the candidate's current level meets the level asked for.

    Being *more* senior than asked is a full match — a Senior Manager can do a
    Manager's job. Being below it scores partially, falling off with distance,
    because a Senior can grow into a Manager role but a trainee cannot.
    """
    _, wanted = split(required_title)
    if not wanted:
        return 1.0

    want_rank = max((_RANK[t] for t in wanted if t in _RANK), default=0)
    have = _tokens(current_level_text(profile)) & SENIORITY
    have_rank = max((_RANK[t] for t in have if t in _RANK), default=0)

    if want_rank == 0 or have_rank == 0:
        # One side states no recognised level; do not penalise on a guess.
        return 1.0
    if have_rank >= want_rank:
        return 1.0
    return max(0.0, 1.0 - 0.25 * (want_rank - have_rank))


def domain_depth(required_title: str, profile: RawProfile) -> float:
    """How much of the candidate's career supports the domain, and how fully.

    Separates a career auditor from someone who audited once a decade ago. Both
    can show the word "audit"; only one of them does the job. A recruiter reads
    this off a CV in seconds and it is what makes their ranking feel right.

    Each role is credited by the *fraction* of the domain it evidences, not by
    whether it touched any of it. For "external audit" that is the whole
    difference between an internal auditor — whose every role carries "audit"
    but never "external" — and someone doing the job that was asked for.
    Crediting a role in full for the shared word ranked the former first.
    """
    domain, _ = split(required_title)
    if not domain or not profile.experience:
        return 1.0
    covered = 0.0
    for item in profile.experience:
        role_tokens = _tokens(" ".join(filter(None, (item.title, item.company))))
        covered += sum(1 for token in domain if _matches(token, role_tokens)) / len(domain)
    return covered / len(profile.experience)


def title_score(required_title: str, profile: RawProfile) -> float:
    """How well this candidate's career matches the role, 0-1.

    Domain is a **gate, not a weight**: a candidate with no evidence of the work
    scores zero however senior they are. That is what stops a Finance Manager
    scoring against a search for an external audit manager.

    Depth then separates candidates who clear the gate. Someone whose whole
    career is the domain outranks someone with one old role in it, which is the
    judgement a recruiter makes without thinking about it.
    """
    domain = domain_match(required_title, profile)
    if domain <= 0:
        return 0.0
    seniority = 1 - _SENIORITY_WEIGHT + _SENIORITY_WEIGHT * seniority_match(
        required_title, profile
    )
    # Depth can halve a score but never zero it — one senior role in the right
    # field still counts for something.
    depth = 0.5 + 0.5 * domain_depth(required_title, profile)
    return domain * seniority * depth


def role_is_in_field(required_title: str, keywords: list[str], item) -> bool:
    """Does this one role count towards "N years in this field"?

    The field is what the recruiter named. Keywords win when they were given —
    a search titled *audit manager* with the keyword *external audit* is asking
    about external audit, and the title is only how the job happens to be
    labelled. With no keywords, the job title's own domain is the subject.

    Judged on the role's title and employer, never on the profile as a whole:
    the question is which *years* count, so it has to be answered per role.
    """
    wanted: set[str] = set()
    for term in keywords or []:
        wanted |= split(term)[0]
    if not wanted:
        wanted = split(required_title)[0]
    if not wanted:
        return True  # nothing was specified, so every role counts

    available = _tokens(" ".join(filter(None, (item.title, item.company))))
    return all(_matches(token, available) for token in wanted)


def missing_domain_words(required_title: str, profile: RawProfile) -> list[str]:
    """The role's domain words with no support anywhere in the career."""
    domain, _ = split(required_title)
    available = _tokens(career_evidence(profile))
    return sorted(token for token in domain if not _matches(token, available))

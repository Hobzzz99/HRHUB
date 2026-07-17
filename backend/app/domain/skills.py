"""Skill normalization and matching.

Exact matching after normalization (lowercasing + a small alias map). Semantic
matching (Backend ≈ Full-Stack, Node ≈ JavaScript) is layered on separately by
`ai_match.py` when AI matching is enabled.
"""

from __future__ import annotations

import re

from app.domain.models import SkillMatch

# Common variants that should be treated as the same skill.
_ALIASES = {
    "js": "javascript",
    "javascript ": "javascript",
    "ts": "typescript",
    "py": "python",
    "reactjs": "react",
    "react.js": "react",
    "node": "node.js",
    "nodejs": "node.js",
    "nextjs": "next.js",
    "golang": "go",
    "postgres": "postgresql",
    "psql": "postgresql",
    "k8s": "kubernetes",
    "gcp": "google cloud",
    "aws cloud": "aws",
    "amazon web services": "aws",
    "ms sql": "sql server",
    "dotnet": ".net",
}

_WS_RE = re.compile(r"\s+")


def normalize_skill(skill: str) -> str:
    text = _WS_RE.sub(" ", skill.strip().lower())
    return _ALIASES.get(text, text)


def normalize_set(skills: list[str]) -> set[str]:
    return {normalize_skill(s) for s in skills if s and s.strip()}


def match_skills(required: list[str], candidate: list[str]) -> SkillMatch:
    """Match required skills against a candidate's skills.

    `matched`/`missing` preserve the recruiter's original spelling of the
    required skills so the UI reads naturally.
    """
    candidate_set = normalize_set(candidate)
    matched: list[str] = []
    missing: list[str] = []
    for req in required:
        if not req or not req.strip():
            continue
        if normalize_skill(req) in candidate_set:
            matched.append(req.strip())
        else:
            missing.append(req.strip())

    total = len(matched) + len(missing)
    ratio = 1.0 if total == 0 else len(matched) / total
    return SkillMatch(matched=matched, missing=missing, ratio=ratio)

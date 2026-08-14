"""Optional AI semantic matching with Claude.

Layered on top of the deterministic score (`scoring.py`), enabled only when
`AI_MATCHING=on` and an API key is set. Claude judges title/skill *equivalence*
that keyword matching misses (Backend Engineer ≈ Backend Developer, Node.js ≈
JavaScript Backend) and returns a semantic score + rationale, which is blended
with the deterministic score.

The caller (`search_runner._maybe_ai_enhance`) wraps this in try/except so any
API failure cleanly falls back to the deterministic score — AI is best-effort.
"""

from __future__ import annotations

import json
import re

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import RawProfile, ScoredCandidate, SearchCriteria

logger = get_logger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = (
    "You are a technical recruiter evaluating how well a candidate matches a role. "
    "Judge semantic equivalence, not just exact keywords: treat related titles and "
    "technologies as matches (e.g. Backend Engineer ~ Backend Developer, Node.js ~ "
    "JavaScript backend, FastAPI ~ Python backend). Respond with ONLY a JSON object, "
    "no prose, matching: "
    '{"semantic_score": <0-100 number>, "reasons": [<short strings>], '
    '"missing": [<required skills or qualities the candidate lacks>]}.'
)


def _build_prompt(profile: RawProfile, criteria: SearchCriteria) -> str:
    return json.dumps(
        {
            "role": {
                "job_title": criteria.job_title,
                "required_keywords": criteria.keywords,
                "min_experience_years": criteria.min_experience,
                "location": criteria.location,
                "keywords": criteria.keywords,
            },
            "candidate": {
                "name": profile.name,
                "current_title": profile.current_title,
                "headline": profile.headline,
                "skills": profile.skills,
                "total_experience_years": _safe_years(profile),
                "about": (profile.about or "")[:600],
            },
        },
        ensure_ascii=False,
    )


def _safe_years(profile: RawProfile) -> float:
    # experience is parsed elsewhere; expose a rough count for the prompt only.
    return float(len(profile.experience))


async def enhance_score(
    scored: ScoredCandidate, profile: RawProfile, criteria: SearchCriteria
) -> ScoredCandidate:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(profile, criteria)}],
    )

    text = next((b.text for b in message.content if b.type == "text"), "")
    match = _JSON_RE.search(text)
    if not match:
        raise ValueError("AI response did not contain JSON")
    data = json.loads(match.group(0))

    semantic = max(0.0, min(100.0, float(data.get("semantic_score", scored.match_score))))
    # Blend deterministic and semantic scores evenly.
    blended = round(0.5 * scored.match_score + 0.5 * semantic, 1)

    ai_reasons = [str(r) for r in data.get("reasons", []) if r][:4]
    ai_missing = [str(m) for m in data.get("missing", []) if m]

    merged_reasons = list(dict.fromkeys([*scored.reasons, *ai_reasons]))
    merged_missing = list(dict.fromkeys([*scored.missing_keywords, *ai_missing]))

    logger.info("ai_enhanced", deterministic=scored.match_score, semantic=semantic)

    return scored.model_copy(
        update={
            "match_score": blended,
            "reasons": merged_reasons,
            "missing_keywords": merged_missing,
            # Record that AI contributed, for reproducibility/analytics.
            "score_version": f"{scored.score_version}+ai",
        }
    )

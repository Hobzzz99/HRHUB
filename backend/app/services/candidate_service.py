"""Candidate persistence: dedupe, cache-aware upsert, and row↔profile mapping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Candidate
from app.domain import experience as experience_mod
from app.domain.models import EducationItem, ExperienceItem, RawProfile


def get_fresh_candidate(
    db: Session, source: str, url: str, *, ttl_days: int | None = None
) -> Candidate | None:
    """Return a stored candidate if it exists and was fetched within the TTL."""
    ttl = settings.profile_ttl_days if ttl_days is None else ttl_days
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.source == source, Candidate.source_profile_url == url
        )
    )
    if candidate is None:
        return None
    cutoff = datetime.now(UTC) - timedelta(days=ttl)
    fetched = candidate.fetched_at
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return candidate if fetched >= cutoff else None


def upsert_candidate(db: Session, raw: RawProfile) -> Candidate:
    """Create or refresh a candidate from a freshly extracted profile."""
    total_years = experience_mod.compute_total_experience_years(raw.experience)

    candidate = db.scalar(
        select(Candidate).where(
            Candidate.source == raw.source,
            Candidate.source_profile_url == raw.source_profile_url,
        )
    )
    if candidate is None:
        candidate = Candidate(
            source=raw.source, source_profile_url=raw.source_profile_url
        )
        db.add(candidate)

    candidate.source_id = raw.source_id
    candidate.name = raw.name
    candidate.headline = raw.headline
    candidate.current_title = raw.current_title
    candidate.current_company = raw.current_company
    candidate.location = raw.location
    candidate.about = raw.about
    candidate.experience = [e.model_dump() for e in raw.experience]
    candidate.education = [e.model_dump() for e in raw.education]
    candidate.skills = list(raw.skills)
    candidate.licenses = list(raw.licenses)
    candidate.certifications = list(raw.certifications)
    candidate.languages = list(raw.languages)
    candidate.total_experience_years = total_years
    candidate.profile_picture_url = raw.profile_picture_url
    candidate.raw = raw.raw
    candidate.fetched_at = datetime.now(UTC)

    db.flush()
    return candidate


def candidate_to_raw_profile(candidate: Candidate) -> RawProfile:
    """Rebuild a `RawProfile` from a stored candidate (for cache-hit scoring)."""
    return RawProfile(
        source=candidate.source,
        source_profile_url=candidate.source_profile_url,
        source_id=candidate.source_id,
        name=candidate.name,
        headline=candidate.headline,
        current_title=candidate.current_title,
        current_company=candidate.current_company,
        location=candidate.location,
        about=candidate.about,
        experience=[ExperienceItem(**e) for e in (candidate.experience or [])],
        education=[EducationItem(**e) for e in (candidate.education or [])],
        skills=list(candidate.skills or []),
        licenses=list(candidate.licenses or []),
        certifications=list(candidate.certifications or []),
        languages=list(candidate.languages or []),
        profile_picture_url=candidate.profile_picture_url,
        raw=candidate.raw,
    )

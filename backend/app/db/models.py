"""SQLAlchemy ORM models.

Candidates are **source-agnostic**: identity is `(source, source_profile_url)`,
never a LinkedIn-specific column, so new providers slot in without schema change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ProviderAccountStatus, SearchStatus


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    # Equal to the Supabase auth user id.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))

    searches: Mapped[list[Search]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    provider_accounts: Mapped[list[ProviderAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProviderAccount(Base, TimestampMixin):
    """A recruiter's linked account for a scraping/API provider.

    Browser session state is stored **encrypted** (Fernet) and is only needed
    when the Playwright provider is enabled.

    A user keeps **one live row per provider** (active or restricted) alongside
    every row they have retired. Retired rows are never deleted because `id`
    seeds the browser fingerprint: keeping them is what stops a replacement
    account presenting the same machine as the account it replaced, which is
    how platforms link one account to the next.
    """

    __tablename__ = "provider_accounts"
    __table_args__ = (
        # Partial unique index rather than a plain constraint: retired rows must
        # be allowed to pile up, but only one may be live at a time. Spelled per
        # dialect because SQLAlchemy has no portable partial index.
        Index(
            "uq_provider_accounts_live",
            "user_id",
            "provider",
            unique=True,
            sqlite_where=text("status <> 'retired'"),
            postgresql_where=text("status <> 'retired'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_session_state: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default=ProviderAccountStatus.ACTIVE, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why this row stopped being usable, shown to the operator in Settings.
    status_reason: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="provider_accounts")


class Search(Base, TimestampMixin):
    __tablename__ = "searches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Requirements
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Legacy. Scoring moved to keywords in v2 and nothing reads this any more;
    #: kept so historical searches still render what the recruiter typed.
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    location: Mapped[str | None] = mapped_column(String(255))
    min_experience: Mapped[float] = mapped_column(Float, default=0.0)
    require_title_match: Mapped[bool] = mapped_column(default=True)
    #: Measure the experience bar against the field being searched for rather
    #: than the whole career.
    experience_in_field: Mapped[bool] = mapped_column(default=True, nullable=False)
    graduation_year_from: Mapped[int | None] = mapped_column(Integer)
    graduation_year_to: Mapped[int | None] = mapped_column(Integer)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    company_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: LinkedIn geo ids from a pasted search URL, the location counterpart
    #: of company_ids.
    location_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    industry: Mapped[str | None] = mapped_column(String(255))
    max_results: Mapped[int] = mapped_column(Integer, default=25)
    min_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    critical_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    enforce_location: Mapped[bool] = mapped_column(default=False)

    # Execution
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    score_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=SearchStatus.QUEUED, nullable=False, index=True
    )
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    #: What the run could not do, when it still produced results — a filter that
    #: never reached LinkedIn, a constraint released to widen a thin search,
    #: profiles that would not open. Distinct from `error`, which means the run
    #: did not finish at all.
    #:
    #: Its absence is the reason a broken scraper and a genuinely empty market
    #: were shown to recruiters as the same sentence.
    degraded_reasons: Mapped[list | None] = mapped_column(JSON)
    #: Set when the recruiter asks a running search to stop. The worker sees it
    #: between profiles and stops cleanly rather than being killed, so the
    #: profiles it has already paid budget for are kept.
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="searches")
    results: Mapped[list[SearchResult]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("source", "source_profile_url"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255))
    source_profile_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(512))
    current_title: Mapped[str | None] = mapped_column(String(255))
    current_company: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    about: Mapped[str | None] = mapped_column(Text)

    experience: Mapped[list[dict]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    licenses: Mapped[list[dict]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[dict]] = mapped_column(JSON, default=list)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)

    total_experience_years: Mapped[float] = mapped_column(Float, default=0.0)
    profile_picture_url: Mapped[str | None] = mapped_column(String(1024))
    raw: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True
    )

    results: Mapped[list[SearchResult]] = relationship(back_populates="candidate")


class SearchResult(Base):
    __tablename__ = "search_results"
    __table_args__ = (UniqueConstraint("search_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )

    match_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_version: Mapped[str] = mapped_column(String(16), nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    search: Mapped[Search] = relationship(back_populates="results")
    candidate: Mapped[Candidate] = relationship(back_populates="results")


class SavedCandidate(Base):
    __tablename__ = "saved_candidates"
    __table_args__ = (UniqueConstraint("user_id", "candidate_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    candidate: Mapped[Candidate] = relationship()

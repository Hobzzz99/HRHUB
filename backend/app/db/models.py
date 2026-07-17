"""SQLAlchemy ORM models.

Candidates are **source-agnostic**: identity is `(source, source_profile_url)`,
never a LinkedIn-specific column, so new providers slot in without schema change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ProviderAccountStatus, SearchStatus


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    searches: Mapped[list["Search"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    provider_accounts: Mapped[list["ProviderAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProviderAccount(Base, TimestampMixin):
    """A recruiter's linked account for a scraping/API provider.

    Credentials and browser session state are stored **encrypted** (Fernet) and
    are only needed when the Playwright provider is enabled.
    """

    __tablename__ = "provider_accounts"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    encrypted_session_state: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default=ProviderAccountStatus.ACTIVE, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="provider_accounts")


class Search(Base, TimestampMixin):
    __tablename__ = "searches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Requirements
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    location: Mapped[str | None] = mapped_column(String(255))
    min_experience: Mapped[float] = mapped_column(Float, default=0.0)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    company: Mapped[str | None] = mapped_column(String(255))
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="searches")
    results: Mapped[list["SearchResult"]] = relationship(
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

    results: Mapped[list["SearchResult"]] = relationship(back_populates="candidate")


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
    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
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

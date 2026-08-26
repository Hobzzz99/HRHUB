"""Request/response schemas for searches and results."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.candidate import CandidateSummary


class SearchCreate(BaseModel):
    job_title: str = Field(min_length=1, max_length=255)
    critical_skills: list[str] = Field(default_factory=list)
    location: str | None = None
    min_experience: float = Field(default=0.0, ge=0)
    require_title_match: bool = True
    graduation_year_from: int | None = Field(default=None, ge=1950, le=2100)
    graduation_year_to: int | None = Field(default=None, ge=1950, le=2100)
    keywords: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list)
    location_ids: list[str] = Field(default_factory=list)
    industry: str | None = None
    max_results: int = Field(default=25, ge=1, le=200)
    min_match_score: float = Field(default=0.0, ge=0, le=100)
    enforce_location: bool = False
    # Optional override; falls back to the server-configured provider.
    provider: str | None = None


class SearchProgress(BaseModel):
    found: int = 0
    to_process: int = 0
    processed: int = 0
    kept: int = 0


class SearchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_title: str
    critical_skills: list[str]
    location: str | None
    min_experience: float
    require_title_match: bool
    graduation_year_from: int | None
    graduation_year_to: int | None
    keywords: list[str]
    companies: list[str]
    company_ids: list[str]
    location_ids: list[str]
    industry: str | None
    max_results: int
    min_match_score: float
    enforce_location: bool
    provider: str
    score_version: str
    status: str
    progress: dict
    error: str | None
    #: Present when the run finished but could not do everything it was asked —
    #: a filter that never reached the platform, profiles that would not open.
    #: The UI must say so rather than showing the ordinary "nobody matched"
    #: message, which blames the recruiter's criteria for a scraper problem.
    degraded_reasons: list[dict] | None = None
    result_count: int = 0
    created_at: datetime
    completed_at: datetime | None


class SearchResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate: CandidateSummary
    match_score: float
    score_version: str
    score_breakdown: dict
    matched_keywords: list[str]
    missing_keywords: list[str]
    reasons: list[str]
    rank: int

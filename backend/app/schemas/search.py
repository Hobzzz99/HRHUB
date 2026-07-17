"""Request/response schemas for searches and results."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.candidate import CandidateSummary


class SearchCreate(BaseModel):
    job_title: str = Field(min_length=1, max_length=255)
    skills: list[str] = Field(default_factory=list)
    critical_skills: list[str] = Field(default_factory=list)
    location: str | None = None
    min_experience: float = Field(default=0.0, ge=0)
    keywords: list[str] = Field(default_factory=list)
    company: str | None = None
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
    skills: list[str]
    critical_skills: list[str]
    location: str | None
    min_experience: float
    keywords: list[str]
    company: str | None
    industry: str | None
    max_results: int
    min_match_score: float
    enforce_location: bool
    provider: str
    score_version: str
    status: str
    progress: dict
    error: str | None
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
    matched_skills: list[str]
    missing_skills: list[str]
    reasons: list[str]
    rank: int

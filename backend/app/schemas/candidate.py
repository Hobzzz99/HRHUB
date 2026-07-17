"""Request/response schemas for candidates and saved candidates."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class CandidateSummary(BaseModel):
    """Compact candidate view used in result cards."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    headline: str | None
    current_title: str | None
    current_company: str | None
    location: str | None
    total_experience_years: float
    profile_picture_url: str | None
    source: str
    source_profile_url: str
    skills: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def top_skills(self) -> list[str]:
        return self.skills[:6]


class CandidateRead(BaseModel):
    """Full candidate detail."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    source_profile_url: str
    name: str
    headline: str | None
    current_title: str | None
    current_company: str | None
    location: str | None
    about: str | None
    experience: list[dict]
    education: list[dict]
    skills: list[str]
    licenses: list[dict]
    certifications: list[dict]
    languages: list[str]
    total_experience_years: float
    profile_picture_url: str | None
    fetched_at: datetime


class SavedCandidateCreate(BaseModel):
    candidate_id: uuid.UUID
    notes: str | None = None


class SavedCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate: CandidateSummary
    notes: str | None
    created_at: datetime

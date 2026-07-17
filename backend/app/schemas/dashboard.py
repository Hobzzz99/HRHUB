"""Dashboard aggregate schema."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.search import SearchRead


class SkillCount(BaseModel):
    skill: str
    count: int


class DashboardStats(BaseModel):
    total_searches: int
    completed_searches: int
    running_searches: int
    saved_candidates: int
    total_candidates_found: int
    average_match_score: float
    top_skills: list[SkillCount]
    recent_searches: list[SearchRead]

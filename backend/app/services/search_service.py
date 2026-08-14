"""Search CRUD, result queries, saved candidates, and dashboard aggregation."""

from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import as_user_uuid
from app.db.enums import SearchStatus
from app.db.models import Candidate, SavedCandidate, Search, SearchResult
from app.domain.models import SearchCriteria
from app.domain.scoring import SCORE_VERSION
from app.schemas.dashboard import DashboardStats, SkillCount
from app.schemas.search import SearchCreate, SearchRead


def criteria_from_search(search: Search) -> SearchCriteria:
    return SearchCriteria(
        job_title=search.job_title,
        critical_skills=list(search.critical_skills or []),
        location=search.location,
        min_experience=search.min_experience or 0.0,
        require_title_match=bool(search.require_title_match),
        graduation_year_from=search.graduation_year_from,
        graduation_year_to=search.graduation_year_to,
        keywords=list(search.keywords or []),
        companies=list(search.companies or []),
        company_ids=list(search.company_ids or []),
        industry=search.industry,
        max_results=search.max_results,
        min_match_score=search.min_match_score or 0.0,
        enforce_location=search.enforce_location,
    )


# --- Create / read searches -------------------------------------------------

def create_search(db: Session, user_id: str, payload: SearchCreate) -> Search:
    search = Search(
        user_id=as_user_uuid(user_id),
        job_title=payload.job_title,
        critical_skills=payload.critical_skills,
        location=payload.location,
        min_experience=payload.min_experience,
        require_title_match=payload.require_title_match,
        graduation_year_from=payload.graduation_year_from,
        graduation_year_to=payload.graduation_year_to,
        keywords=payload.keywords,
        companies=payload.companies,
        company_ids=payload.company_ids,
        industry=payload.industry,
        max_results=payload.max_results,
        min_match_score=payload.min_match_score,
        enforce_location=payload.enforce_location,
        provider=(payload.provider or settings.provider),
        score_version=SCORE_VERSION,
        status=SearchStatus.QUEUED,
        progress={"found": 0, "to_process": 0, "processed": 0, "kept": 0},
    )
    db.add(search)
    db.commit()
    db.refresh(search)
    return search


def get_search(db: Session, user_id: str, search_id: uuid.UUID) -> Search | None:
    return db.scalar(
        select(Search).where(
            Search.id == search_id, Search.user_id == as_user_uuid(user_id)
        )
    )


def result_count(db: Session, search_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count(SearchResult.id)).where(SearchResult.search_id == search_id)
    ) or 0


def to_search_read(db: Session, search: Search) -> SearchRead:
    read = SearchRead.model_validate(search)
    read.result_count = result_count(db, search.id)
    return read


def list_searches(db: Session, user_id: str, limit: int = 20) -> list[SearchRead]:
    searches = db.scalars(
        select(Search)
        .where(Search.user_id == as_user_uuid(user_id))
        .order_by(Search.created_at.desc())
        .limit(limit)
    ).all()
    return [to_search_read(db, s) for s in searches]


def get_results(db: Session, search_id: uuid.UUID) -> list[SearchResult]:
    return db.scalars(
        select(SearchResult)
        .where(SearchResult.search_id == search_id)
        .options(selectinload(SearchResult.candidate))
        .order_by(SearchResult.rank.asc(), SearchResult.match_score.desc())
    ).all()


# --- Candidates / saved -----------------------------------------------------

def get_candidate(db: Session, candidate_id: uuid.UUID) -> Candidate | None:
    return db.get(Candidate, candidate_id)


def save_candidate(
    db: Session, user_id: str, candidate_id: uuid.UUID, notes: str | None
) -> SavedCandidate:
    uid = as_user_uuid(user_id)
    existing = db.scalar(
        select(SavedCandidate).where(
            SavedCandidate.user_id == uid, SavedCandidate.candidate_id == candidate_id
        )
    )
    if existing:
        existing.notes = notes
        db.commit()
        db.refresh(existing)
        return existing
    saved = SavedCandidate(user_id=uid, candidate_id=candidate_id, notes=notes)
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


def unsave_candidate(db: Session, user_id: str, candidate_id: uuid.UUID) -> bool:
    saved = db.scalar(
        select(SavedCandidate).where(
            SavedCandidate.user_id == as_user_uuid(user_id),
            SavedCandidate.candidate_id == candidate_id,
        )
    )
    if not saved:
        return False
    db.delete(saved)
    db.commit()
    return True


def list_saved(db: Session, user_id: str) -> list[SavedCandidate]:
    return db.scalars(
        select(SavedCandidate)
        .where(SavedCandidate.user_id == as_user_uuid(user_id))
        .options(selectinload(SavedCandidate.candidate))
        .order_by(SavedCandidate.created_at.desc())
    ).all()


# --- Dashboard --------------------------------------------------------------

def dashboard(db: Session, user_id: str) -> DashboardStats:
    uid = as_user_uuid(user_id)

    total = db.scalar(select(func.count(Search.id)).where(Search.user_id == uid)) or 0
    completed = db.scalar(
        select(func.count(Search.id)).where(
            Search.user_id == uid, Search.status == SearchStatus.COMPLETED
        )
    ) or 0
    running = db.scalar(
        select(func.count(Search.id)).where(
            Search.user_id == uid,
            Search.status.in_([SearchStatus.QUEUED, SearchStatus.RUNNING]),
        )
    ) or 0
    saved = db.scalar(
        select(func.count(SavedCandidate.id)).where(SavedCandidate.user_id == uid)
    ) or 0

    results_q = (
        select(SearchResult)
        .join(Search, Search.id == SearchResult.search_id)
        .where(Search.user_id == uid)
    )
    result_rows = db.scalars(
        results_q.options(selectinload(SearchResult.candidate))
    ).all()

    candidate_ids = {r.candidate_id for r in result_rows}
    avg_score = (
        round(sum(r.match_score for r in result_rows) / len(result_rows), 1)
        if result_rows
        else 0.0
    )

    skill_counter: Counter[str] = Counter()
    for row in result_rows:
        if row.candidate and row.candidate.skills:
            skill_counter.update(row.candidate.skills)
    top_skills = [SkillCount(skill=s, count=c) for s, c in skill_counter.most_common(10)]

    recent = list_searches(db, user_id, limit=5)

    return DashboardStats(
        total_searches=total,
        completed_searches=completed,
        running_searches=running,
        saved_candidates=saved,
        total_candidates_found=len(candidate_ids),
        average_match_score=avg_score,
        top_skills=top_skills,
        recent_searches=recent,
    )

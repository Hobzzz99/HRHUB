"""Search endpoints: create, status, results, live SSE stream, export."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_authed_user
from app.core.security import CurrentUser
from app.db.enums import SearchStatus
from app.db.session import SessionLocal, get_db
from app.schemas.search import SearchCreate, SearchRead, SearchResultRead
from app.services import search_service
from app.workers.tasks import run_search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchRead, status_code=status.HTTP_202_ACCEPTED)
def create_search(
    payload: SearchCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> SearchRead:
    """Create a search and queue the background job."""
    search = search_service.create_search(db, user.id, payload)
    run_search.delay(str(search.id))
    return search_service.to_search_read(db, search)


@router.get("", response_model=list[SearchRead])
def list_searches(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> list[SearchRead]:
    return search_service.list_searches(db, user.id, limit=limit)


def _get_owned_search(db: Session, user: CurrentUser, search_id: uuid.UUID):
    search = search_service.get_search(db, user.id, search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return search


@router.get("/{search_id}", response_model=SearchRead)
def get_search(
    search_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> SearchRead:
    search = _get_owned_search(db, user, search_id)
    return search_service.to_search_read(db, search)


@router.get("/{search_id}/results", response_model=list[SearchResultRead])
def get_results(
    search_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> list[SearchResultRead]:
    _get_owned_search(db, user, search_id)
    return search_service.get_results(db, search_id)


@router.get("/{search_id}/stream")
async def stream_search(
    search_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_authed_user),
) -> EventSourceResponse:
    """Server-Sent Events stream of live status + progress until the job ends."""
    user_id = user.id

    async def event_generator():
        last_payload: str | None = None
        # Cap total lifetime so a stuck job can't hold the connection forever.
        for _ in range(600):
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                search = search_service.get_search(db, user_id, search_id)
                if search is None:
                    yield {"event": "error", "data": json.dumps({"detail": "not found"})}
                    return
                payload = json.dumps(
                    {
                        "status": search.status,
                        "progress": search.progress or {},
                        "result_count": search_service._result_count(db, search.id),
                        "error": search.error,
                    }
                )
                terminal = SearchStatus(search.status).is_terminal
            finally:
                db.close()

            if payload != last_payload:
                yield {"event": "status", "data": payload}
                last_payload = payload
            if terminal:
                return
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_generator())


@router.get("/{search_id}/export")
def export_results(
    search_id: uuid.UUID,
    fmt: str = Query("csv", pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
):
    """Export a search's ranked results as CSV or JSON."""
    _get_owned_search(db, user, search_id)
    results = search_service.get_results(db, search_id)

    rows = [
        {
            "rank": r.rank,
            "name": r.candidate.name,
            "headline": r.candidate.headline,
            "current_company": r.candidate.current_company,
            "location": r.candidate.location,
            "experience_years": r.candidate.total_experience_years,
            "match_score": r.match_score,
            "matched_skills": ", ".join(r.matched_skills or []),
            "missing_skills": ", ".join(r.missing_skills or []),
            "profile_url": r.candidate.source_profile_url,
        }
        for r in results
    ]

    if fmt == "json":
        return rows

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(rows[0].keys())
        if rows
        else ["rank", "name", "match_score", "profile_url"],
    )
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="search-{search_id}.csv"'},
    )

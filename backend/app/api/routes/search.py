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
from app.workers import routing
from app.workers.tasks import run_search

router = APIRouter(prefix="/search", tags=["search"])

#: How often the live stream re-reads the search row, and how long it keeps
#: doing so before hanging up, so a stuck job cannot hold the connection open
#: forever. NOTE: a scrape-backed search runs 30-60s per profile, so a full
#: 20-profile run outlives this window and the client must reconnect.
_STREAM_POLL_INTERVAL_S = 1.0
_STREAM_MAX_DURATION_S = 600


@router.post("", response_model=SearchRead, status_code=status.HTTP_202_ACCEPTED)
def create_search(
    payload: SearchCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> SearchRead:
    """Create a search and queue the background job on the owner's own worker."""
    search = search_service.create_search(db, user.id, payload)
    # Routed rather than broadcast: scraping uses this recruiter's own LinkedIn
    # session, signed in by hand on their own machine. See workers/routing.py.
    run_search.apply_async(args=[str(search.id)], queue=routing.user_queue(user.id))
    return search_service.to_search_read(db, search)


@router.post("/{search_id}/cancel", response_model=SearchRead)
def cancel_search(
    search_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> SearchRead:
    """Stop a search the recruiter did not mean to start.

    Enter submits the form, so a half-filled search begins on a misclick and
    then spends real budget against a real LinkedIn account for minutes.

    A queued search stops at once. A running one is asked to stop and does so
    between profiles — the profile in flight has already been charged to the
    hourly budget, and abandoning it mid-way would waste a slot that takes an
    hour to come back.
    """
    search = search_service.request_cancel(db, user.id, search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="Search not found")
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
        for _ in range(int(_STREAM_MAX_DURATION_S / _STREAM_POLL_INTERVAL_S)):
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
                        "result_count": search_service.result_count(db, search.id),
                        "error": search.error,
                        # Both stream shapes must carry this or the UI silently
                        # falls back to "no candidates matched" for a run whose
                        # filters never applied.
                        "degraded_reasons": search.degraded_reasons,
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
            await asyncio.sleep(_STREAM_POLL_INTERVAL_S)

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
            "matched_keywords": ", ".join(r.matched_keywords or []),
            "missing_keywords": ", ".join(r.missing_keywords or []),
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

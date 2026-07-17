"""Candidate detail and save/unsave endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_authed_user
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.candidate import (
    CandidateRead,
    SavedCandidateCreate,
    SavedCandidateRead,
)
from app.services import search_service

router = APIRouter(tags=["candidates"])


@router.get("/candidate/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> CandidateRead:
    candidate = search_service.get_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post(
    "/candidate/save",
    response_model=SavedCandidateRead,
    status_code=status.HTTP_201_CREATED,
)
def save_candidate(
    payload: SavedCandidateCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> SavedCandidateRead:
    if search_service.get_candidate(db, payload.candidate_id) is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return search_service.save_candidate(db, user.id, payload.candidate_id, payload.notes)


@router.delete("/candidate/save/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsave_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> None:
    if not search_service.unsave_candidate(db, user.id, candidate_id):
        raise HTTPException(status_code=404, detail="Not saved")


@router.get("/saved", response_model=list[SavedCandidateRead])
def list_saved(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> list[SavedCandidateRead]:
    return search_service.list_saved(db, user.id)

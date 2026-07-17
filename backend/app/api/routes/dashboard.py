"""Dashboard aggregate endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_authed_user
from app.core.security import CurrentUser
from app.db.session import get_db
from app.schemas.dashboard import DashboardStats
from app.services import search_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardStats)
def get_dashboard(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> DashboardStats:
    return search_service.dashboard(db, user.id)

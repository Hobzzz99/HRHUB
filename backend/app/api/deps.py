"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.db.session import get_db
from app.services.user_service import ensure_user


def get_authed_user(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Authenticated user, guaranteed to have a local `users` row."""
    ensure_user(db, user.id, user.email)
    db.commit()
    return user

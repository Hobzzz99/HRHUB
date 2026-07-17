"""User provisioning.

Searches and saved candidates reference a `users` row. Because identity is owned
by Supabase, we lazily upsert a local user record on first authenticated use.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import User


def ensure_user(db: Session, user_id: str, email: str | None) -> User:
    uid = uuid.UUID(str(user_id))
    user = db.get(User, uid)
    if user is None:
        user = User(id=uid, email=email or f"{uid}@unknown.local")
        db.add(user)
        db.flush()
    elif email and user.email != email:
        user.email = email
        db.flush()
    return user

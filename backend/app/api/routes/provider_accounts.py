"""Provider-account credentials (opt-in Playwright provider only).

Stores LinkedIn credentials encrypted at rest. Only relevant when
`PROVIDER=playwright`. See COMPLIANCE.md before using.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_authed_user
from app.core.security import CurrentUser
from app.db.session import get_db
from app.services import provider_account_service

router = APIRouter(prefix="/provider-account", tags=["provider-account"])


class CredentialsIn(BaseModel):
    provider: str = Field(default="linkedin")
    username: str
    password: str


class ProviderAccountOut(BaseModel):
    provider: str
    status: str
    has_session: bool


@router.post("", response_model=ProviderAccountOut, status_code=status.HTTP_201_CREATED)
def set_credentials(
    payload: CredentialsIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> ProviderAccountOut:
    account = provider_account_service.set_credentials(
        db, user.id, payload.provider, payload.username, payload.password
    )
    return ProviderAccountOut(
        provider=account.provider,
        status=account.status,
        has_session=bool(account.encrypted_session_state),
    )


@router.get("/{provider}", response_model=ProviderAccountOut | None)
def get_account(
    provider: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> ProviderAccountOut | None:
    account = provider_account_service.get_account(db, user.id, provider)
    if account is None:
        return None
    return ProviderAccountOut(
        provider=account.provider,
        status=account.status,
        has_session=bool(account.encrypted_session_state),
    )

"""Authentication: verify Supabase-issued JWTs and resolve the current user.

Supports both Supabase project styles:
  * Legacy HS256 — verified with `SUPABASE_JWT_SECRET`.
  * Asymmetric RS256/ES256 — verified against `SUPABASE_JWKS_URL`.

In local dev, `AUTH_DISABLED=true` short-circuits verification and injects a fixed
dev user so the app runs end-to-end without configuring Supabase.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# auto_error=False so we can allow the dev bypass when no header is present.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None = None


def as_user_uuid(user_id: str) -> uuid.UUID:
    """Parse a user id into the UUID the `users.id` column stores.

    Ids arrive as the string `sub` claim of a JWT, but every query compares them
    against a UUID column. Doing the conversion in one named place keeps that
    coupling visible instead of scattering `uuid.UUID(...)` through the services.

    ``str()`` first because callers also pass ORM `UUID` columns straight through
    (`search_runner` hands over `search.user_id`), and `uuid.UUID` rejects those.
    """
    return uuid.UUID(str(user_id))


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(settings.supabase_jwks_url)


def _decode_token(token: str) -> dict:
    options = {"verify_aud": bool(settings.supabase_jwt_audience)}
    audience = settings.supabase_jwt_audience or None
    issuer = settings.supabase_jwt_issuer or None

    if settings.supabase_jwt_secret:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=issuer,
            options=options,
        )
    if settings.supabase_jwks_url:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=audience,
            issuer=issuer,
            options=options,
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Auth is enabled but no SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL is set.",
    )


def _dev_user() -> CurrentUser:
    return CurrentUser(id=settings.dev_user_id, email=settings.dev_user_email)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """FastAPI dependency: returns the authenticated user or raises 401."""
    if settings.auth_disabled and not settings.is_prod:
        return _dev_user()

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = _decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        logger.warning("jwt_verification_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim.",
        )
    return CurrentUser(id=user_id, email=claims.get("email"))

"""Health and readiness."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "provider": settings.provider,
        "ai_matching": settings.ai_matching,
    }

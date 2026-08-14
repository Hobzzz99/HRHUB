"""Health and readiness.

Two endpoints with different jobs, because conflating them made the deployment
gate useless:

* ``/health`` — is this process alive? Cheap, no dependencies, safe to poll.
* ``/ready`` — can it actually serve? Checks the database and Redis.

``DEPLOYMENT.md`` gates a deploy on the health check, and until now that check
was a static dict: it returned 200 with Postgres down, with Redis down, and
with migrations unapplied — the exact three failures it was being run to rule
out.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness. Deliberately dependency-free, so a database blip does not make
    an orchestrator kill a process that is merely waiting for it."""
    return {
        "status": "ok",
        "version": __version__,
        "provider": settings.provider,
        "ai_matching": settings.ai_matching,
    }


def _check_database() -> str | None:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        return str(exc)[:200]
    finally:
        db.close()


def _check_redis() -> str | None:
    """Redis carries the job queue, so the API can look fine while no search
    a recruiter starts will ever reach a worker."""
    try:
        import redis  # imported here so a missing extra cannot break liveness

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        client.ping()
        return None
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        return str(exc)[:200]


@router.get("/ready")
def ready(response: Response) -> dict:
    """Readiness. 503 when a dependency is down, so it can gate a deployment."""
    checks = {"database": _check_database(), "redis": _check_redis()}
    failed = {name: error for name, error in checks.items() if error}

    if failed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning("readiness_failed", failed=list(failed))

    return {
        "status": "ok" if not failed else "degraded",
        "version": __version__,
        "checks": {name: ("ok" if not error else error) for name, error in checks.items()},
    }

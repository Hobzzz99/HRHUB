"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import candidates, dashboard, health, provider_accounts, search
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.services import stale_searches

logger = get_logger(__name__)

#: How often to look for searches whose worker died. Frequent enough that a
#: recruiter is not left watching a dead progress bar for long, rare enough to
#: be invisible — the query is a single indexed lookup on `status`.
_SWEEP_INTERVAL_S = 300


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the stale-search sweep for as long as the API is up.

    Lives here rather than in a scheduler because it needs no scheduler: the API
    is the one process guaranteed to be running. The workers are laptops that
    come and go, which is the very thing being swept up after.
    """

    async def sweep_forever() -> None:
        while True:
            try:
                with session_scope() as db:
                    reaped = stale_searches.sweep(db)
                if reaped:
                    logger.warning("stale_searches_reaped", count=reaped)
            except Exception:  # noqa: BLE001 — a bad sweep must not stop the API
                logger.exception("stale_search_sweep_failed")
            await asyncio.sleep(_SWEEP_INTERVAL_S)

    task = asyncio.create_task(sweep_forever())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        lifespan=lifespan,
        title="Candidate Search Platform API",
        version=__version__,
        description=(
            "Search, score, and rank candidates from a pluggable data provider. "
            "See COMPLIANCE.md before enabling the LinkedIn scraping provider."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(candidates.router)
    app.include_router(dashboard.router)
    app.include_router(provider_accounts.router)

    logger.info("app_started", provider=settings.provider, env=settings.app_env)
    return app


app = create_app()

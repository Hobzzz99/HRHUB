"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.api.routes import candidates, dashboard, health, provider_accounts, search

logger = get_logger(__name__)


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
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

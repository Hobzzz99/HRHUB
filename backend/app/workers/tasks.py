"""Celery tasks."""

from __future__ import annotations

import asyncio
import uuid

from app.core.logging import get_logger
from app.services.search_runner import execute_search
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="run_search", bind=True, max_retries=2, default_retry_delay=10)
def run_search(self, search_id: str) -> str:
    """Execute a queued search end-to-end. Idempotent per search id."""
    logger.info("run_search_started", search_id=search_id, task_id=self.request.id)
    asyncio.run(execute_search(uuid.UUID(search_id)))
    logger.info("run_search_finished", search_id=search_id)
    return search_id

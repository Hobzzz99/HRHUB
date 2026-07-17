"""Celery application.

The worker runs in its own process/container (with Playwright available). Search
jobs are queued from the API and consumed here, isolating browser automation and
CPU-bound scoring from the request/response path.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "candidate_search",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_max_tasks_per_child=50,  # recycle workers to bound browser resource leaks
    task_acks_late=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
)

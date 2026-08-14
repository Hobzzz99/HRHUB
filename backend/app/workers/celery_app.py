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
    # Ack after the run, so a worker killed mid-search does not lose the job.
    task_acks_late=True,
    # ...but do NOT hand that job to anyone else. Re-running a search is not
    # free and not idempotent: it re-opens profiles, re-spending an hourly
    # budget that takes an hour to refill, and then fails on the unique
    # (search_id, candidate_id) constraint because the first attempt already
    # stored its results — surfacing to the recruiter as a completed search
    # reverting to running and then dying with a database error.
    #
    # A search whose worker died is instead left for the stale-run sweep to
    # mark failed, which the recruiter can re-run deliberately, reusing the
    # cached profiles the dead run already paid for.
    task_reject_on_worker_lost=False,
    # Nothing bounds a run from outside otherwise. A hung navigation, or the
    # rate limiter sleeping for its 600s ceiling, would hold the worker
    # indefinitely — and with --pool=solo (one browser per recruiter) that
    # blocks every other search on that laptop.
    task_time_limit=settings.scrape_task_time_limit_s,
    task_soft_time_limit=settings.scrape_task_time_limit_s - 60,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
)

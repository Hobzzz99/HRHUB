"""A search must run on its owner's machine, not on whichever worker is free.

Each recruiter scrapes with their own LinkedIn account, signed in by hand on
their own laptop. Celery's default — every worker draining one shared queue —
would hand a search to a colleague's machine, which then loads the originating
recruiter's stored session into a different browser on a different IP. That is
both unusable and the behaviour most likely to get the account restricted.
"""

from __future__ import annotations

from app.core.config import settings
from app.workers import routing


def test_user_queue_is_specific_to_the_user():
    assert routing.user_queue("abc") != routing.user_queue("def")
    assert routing.user_queue("abc") == routing.user_queue("abc")


def test_user_queue_is_not_the_shared_queue():
    """A worker listening only to its own queue must not receive shared work."""
    assert routing.user_queue("abc") != routing.SHARED_QUEUE


def test_search_is_queued_to_its_owner(client, monkeypatch):
    """The API must route by owner rather than broadcast."""
    sent: dict[str, object] = {}

    def fake_apply_async(args=None, queue=None, **kwargs):
        sent["args"] = args
        sent["queue"] = queue

    monkeypatch.setattr("app.api.routes.search.run_search.apply_async", fake_apply_async)

    resp = client.post(
        "/search",
        json={"job_title": "External Audit Manager", "max_results": 5},
    )
    assert resp.status_code == 202

    search_id = resp.json()["id"]
    assert sent["args"] == [search_id]
    assert sent["queue"] == routing.user_queue(settings.dev_user_id)

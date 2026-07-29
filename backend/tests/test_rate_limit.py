"""Tests for the persistent sliding-window scrape limiter.

The limiter is the control that actually protects the LinkedIn account, so the
properties worth pinning down are: it never hands out more than the limit, and
the budget survives a process restart.
"""

from __future__ import annotations

import json
import time

import pytest

from app.providers.rate_limit import RateLimitExceeded, SlidingWindowLimiter


def _limiter(tmp_path, *, limit=3, window_s=3600.0) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        limit=limit,
        window_s=window_s,
        state_path=tmp_path / "state" / "rate.json",
        key="linkedin_profiles",
    )


async def test_allows_exactly_the_limit_then_refuses(tmp_path):
    limiter = _limiter(tmp_path, limit=3)
    for _ in range(3):
        assert await limiter.acquire(max_wait_s=0) == 0.0
    with pytest.raises(RateLimitExceeded):
        await limiter.acquire(max_wait_s=0)


async def test_refusal_reports_when_the_next_slot_frees_up(tmp_path):
    limiter = _limiter(tmp_path, limit=1, window_s=1800.0)
    await limiter.acquire(max_wait_s=0)
    with pytest.raises(RateLimitExceeded) as exc:
        await limiter.acquire(max_wait_s=0)
    assert 1700 < exc.value.retry_after_s <= 1800
    assert "1 profiles per 30 min" in str(exc.value)


async def test_budget_survives_a_restart(tmp_path):
    # Spending the budget then constructing a fresh limiter models the worker
    # being restarted mid-hour: an in-memory counter would reset here.
    first = _limiter(tmp_path, limit=2)
    await first.acquire(max_wait_s=0)
    await first.acquire(max_wait_s=0)

    second = _limiter(tmp_path, limit=2)
    assert second.snapshot().used == 2
    with pytest.raises(RateLimitExceeded):
        await second.acquire(max_wait_s=0)


async def test_slots_expire_once_they_leave_the_window(tmp_path):
    limiter = _limiter(tmp_path, limit=2, window_s=0.25)
    await limiter.acquire(max_wait_s=0)
    await limiter.acquire(max_wait_s=0)
    with pytest.raises(RateLimitExceeded):
        await limiter.acquire(max_wait_s=0)

    time.sleep(0.3)
    assert limiter.snapshot().used == 0
    assert await limiter.acquire(max_wait_s=0) == 0.0


async def test_waits_for_a_slot_when_allowed_to(tmp_path):
    limiter = _limiter(tmp_path, limit=1, window_s=0.5)
    await limiter.acquire(max_wait_s=0)
    waited = await limiter.acquire(max_wait_s=5.0)
    assert waited > 0
    assert limiter.snapshot().used == 1


async def test_snapshot_reports_usage_and_reset(tmp_path):
    limiter = _limiter(tmp_path, limit=3, window_s=600.0)
    assert limiter.snapshot().remaining == 3
    await limiter.acquire(max_wait_s=0)
    snapshot = limiter.snapshot()
    assert (snapshot.used, snapshot.remaining, snapshot.limit) == (1, 2, 3)
    # Nothing to reset while the budget is not spent.
    assert snapshot.resets_in_s == 0.0

    await limiter.acquire(max_wait_s=0)
    await limiter.acquire(max_wait_s=0)
    spent = limiter.snapshot()
    assert spent.remaining == 0
    assert 0 < spent.resets_in_s <= 600


async def test_a_corrupt_state_file_does_not_crash_the_run(tmp_path):
    limiter = _limiter(tmp_path, limit=2)
    path = tmp_path / "state" / "rate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    # An unreadable window reads as empty. That is the safe-for-the-app choice
    # but NOT the safe-for-the-account one, so it must at least still work.
    assert await limiter.acquire(max_wait_s=0) == 0.0
    assert limiter.snapshot().used == 1


async def test_other_keys_in_the_state_file_are_preserved(tmp_path):
    path = tmp_path / "state" / "rate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"something_else": [1, 2, 3]}), encoding="utf-8")

    limiter = _limiter(tmp_path, limit=2)
    await limiter.acquire(max_wait_s=0)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["something_else"] == [1, 2, 3]
    assert len(stored["linkedin_profiles"]) == 1


async def test_stale_timestamps_are_pruned_from_disk(tmp_path):
    path = tmp_path / "state" / "rate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = time.time() - 7200
    path.write_text(json.dumps({"linkedin_profiles": [old, old + 1]}), encoding="utf-8")

    limiter = _limiter(tmp_path, limit=2, window_s=3600.0)
    assert limiter.snapshot().used == 0
    await limiter.acquire(max_wait_s=0)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored["linkedin_profiles"]) == 1


def test_a_limit_below_one_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        SlidingWindowLimiter(limit=0, window_s=60, state_path=tmp_path / "x.json")


async def test_default_limiter_is_twenty_an_hour():
    from app.providers.playwright_linkedin import default_limiter

    snapshot = default_limiter().snapshot()
    assert snapshot.limit == 20
    assert snapshot.window_s == 3600

"""A persistent sliding-window throttle on how many profiles get opened.

This is the single most important safety control in the scraping path. Volume
is what LinkedIn's abuse detection actually keys on — an account that opens
hundreds of profiles an hour is caught regardless of how convincing its mouse
movements are.

**The window is stored on disk, not in memory.** An in-memory counter resets
every time the worker restarts, so a crash loop (or an impatient re-run) would
quietly hand out a fresh budget each time and defeat the whole limit. The file
keeps the last hour's timestamps so the budget survives restarts.

Concurrency: an in-process ``asyncio.Lock`` serialises the read-modify-write,
and the file is replaced atomically. Two *separate* worker processes racing on
the same file can each land a slot in the same instant, so the effective ceiling
across N processes is the limit plus at most N-1. The provider runs one browser
per search, so in practice this is one writer; if you scale to several workers,
lower ``SCRAPE_MAX_PROFILES_PER_HOUR`` to match rather than relying on the file
to arbitrate.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(RuntimeError):
    """The hourly budget is spent and waiting for a slot would take too long.

    Carries ``retry_after_s`` so callers can tell the user when the next profile
    becomes available instead of just failing.
    """

    def __init__(self, message: str, *, retry_after_s: float) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LimiterSnapshot:
    """A read-only view of the budget, for progress reporting and diagnostics."""

    used: int
    limit: int
    window_s: float
    #: Seconds until the oldest slot expires; 0 when the budget is not spent.
    resets_in_s: float

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def budget_for(provider: str) -> SlidingWindowLimiter:
    """The hourly profile budget for one platform.

    Each platform gets its **own** key in the shared state file. A budget shared
    across platforms would make a busy LinkedIn run silently starve an Indeed
    one, and the limit exists to protect one account on one site — it is not a
    global throughput cap.
    """
    from app.core.config import settings

    return SlidingWindowLimiter(
        limit=settings.scrape_max_profiles_per_hour,
        window_s=settings.scrape_rate_limit_window_s,
        state_path=Path(settings.scrape_state_dir) / "scrape_rate_limit.json",
        key=f"{provider}_profiles",
    )


class SlidingWindowLimiter:
    """At most ``limit`` acquisitions in any rolling ``window_s`` seconds."""

    def __init__(
        self,
        *,
        limit: int,
        window_s: float,
        state_path: Path | str,
        key: str = "default",
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._limit = limit
        self._window_s = float(window_s)
        self._path = Path(state_path)
        self._key = key
        self._lock = asyncio.Lock()

    # --- persistence -------------------------------------------------------

    def _load(self) -> list[float]:
        """Timestamps still inside the window, oldest first."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        stamps = raw.get(self._key, []) if isinstance(raw, dict) else []
        cutoff = time.time() - self._window_s
        return sorted(
            float(s) for s in stamps if isinstance(s, (int, float)) and float(s) > cutoff
        )

    def _save(self, stamps: list[float]) -> None:
        """Rewrite the state file atomically, preserving other keys."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
        except (OSError, ValueError):
            raw = {}
        raw[self._key] = stamps
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-replace: a crash mid-write must not leave a truncated
            # file, because an unreadable file reads back as an empty budget.
            temp = self._path.with_suffix(f".{os.getpid()}.tmp")
            temp.write_text(json.dumps(raw), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError:
            logger.warning("rate_limit_state_write_failed", path=str(self._path), exc_info=True)

    # --- api ---------------------------------------------------------------

    def snapshot(self) -> LimiterSnapshot:
        stamps = self._load()
        resets_in = 0.0
        if len(stamps) >= self._limit:
            resets_in = max(0.0, stamps[0] + self._window_s - time.time())
        return LimiterSnapshot(
            used=len(stamps),
            limit=self._limit,
            window_s=self._window_s,
            resets_in_s=resets_in,
        )

    async def acquire(self, *, max_wait_s: float = 0.0) -> float:
        """Reserve one slot, waiting up to ``max_wait_s`` for one to free up.

        Returns how long it waited. Raises :class:`RateLimitExceeded` when the
        next slot is further away than ``max_wait_s`` — the caller decides
        whether that ends the run or just this profile.
        """
        waited = 0.0
        while True:
            async with self._lock:
                stamps = self._load()
                if len(stamps) < self._limit:
                    stamps.append(time.time())
                    self._save(stamps)
                    logger.info(
                        "rate_limit_slot_taken",
                        used=len(stamps),
                        limit=self._limit,
                        waited_s=round(waited, 1),
                    )
                    return waited
                # Budget spent: the oldest timestamp leaving the window is the
                # earliest moment another profile may be opened.
                wait_for = max(0.0, stamps[0] + self._window_s - time.time())

            if wait_for <= 0:
                # The slot expired between the two statements above; retry.
                continue
            if waited + wait_for > max_wait_s:
                raise RateLimitExceeded(
                    f"Hourly scrape limit reached ({self._limit} profiles per "
                    f"{int(self._window_s / 60)} min). The next slot frees up in "
                    f"{int(wait_for)}s.",
                    retry_after_s=wait_for,
                )
            logger.info("rate_limit_waiting", seconds=round(wait_for, 1))
            await asyncio.sleep(wait_for + 0.25)
            waited += wait_for + 0.25

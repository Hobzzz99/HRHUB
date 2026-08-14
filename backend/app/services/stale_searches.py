"""Finding searches whose worker died, and telling the truth about them.

`execute_search` moves a search out of `running` from inside the process that
is running it — completed, failed, restricted. Every one of those paths needs
that process to still exist. When it does not, because a laptop lid closed, the
worker was killed, or Chromium exhausted memory, **nothing writes a terminal
status at all.**

The row then says `running` forever. The recruiter watches a progress bar that
will never move, the dashboard counts it as work in flight, and there is no way
to tell it apart from a search that is merely slow — scrape-backed runs take
minutes, so "still going" is entirely plausible.

This is the out-of-process half of the same promise the rest of the pipeline
keeps: a search must always reach a state that says what happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import SearchStatus
from app.db.models import Search

logger = get_logger(__name__)

_MESSAGE = (
    "This search stopped unexpectedly — the machine running it went away "
    "before it finished. Anything it had already collected has been kept, and "
    "re-running it will reuse those profiles rather than spending budget on "
    "them again."
)


def sweep(db: Session, *, older_than_s: int | None = None) -> int:
    """Mark long-abandoned `running` searches as failed. Returns how many.

    Age is measured from `updated_at`, which every progress write touches — so a
    search that is slow but alive keeps refreshing it and is never swept, while
    one whose worker died stops moving immediately.
    """
    cutoff_s = older_than_s if older_than_s is not None else settings.stale_search_after_s
    cutoff = datetime.now(UTC) - timedelta(seconds=cutoff_s)

    stale = db.scalars(
        select(Search).where(
            Search.status == SearchStatus.RUNNING,
            Search.updated_at < cutoff,
        )
    ).all()

    for search in stale:
        logger.warning(
            "stale_search_reaped",
            search_id=str(search.id),
            last_update=search.updated_at.isoformat(),
        )
        search.status = SearchStatus.FAILED
        search.error = _MESSAGE
        search.completed_at = datetime.now(UTC)

    if stale:
        db.commit()
    return len(stale)

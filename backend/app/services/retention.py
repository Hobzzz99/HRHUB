"""Deleting candidate data, and not keeping it longer than it is useful.

COMPLIANCE.md commits to three things that were never built: "a retention
policy, and a deletion/DSAR path", "add a purge job for production", and — of
`Candidate.raw`, the entire unfiltered provider payload — "prune it in
production".

Until now the only DELETE in the API removed a *bookmark*; the profile itself
survived untouched, and there was no route, CLI, or script that removed a
person at all. Answering "please delete me" meant hand-written SQL against
production Postgres over an SSH tunnel, with no audit trail and no record that
it had happened.

Two jobs, kept separate because they answer to different things:

* :func:`forget_candidate` — a request from a person. Immediate and complete.
* :func:`purge_expired` — routine hygiene. Drops the debugging payload from
  profiles nobody is using, and removes candidates no search still references.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Candidate, SavedCandidate, SearchResult

logger = get_logger(__name__)


def forget_candidate(db: Session, candidate_id) -> bool:
    """Erase one person entirely. True if they existed.

    Deletes the profile itself; `search_results` and `saved_candidates` follow
    through their `ondelete="CASCADE"`, so no shortlist keeps a copy of somebody
    who asked to be removed.

    Logged deliberately — a deletion request needs to leave evidence that it was
    honoured, and the row that would have proved it is the row being destroyed.
    """
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        return False

    logger.warning(
        "candidate_forgotten",
        candidate_id=str(candidate_id),
        source=candidate.source,
        url=candidate.source_profile_url,
    )

    # A Core delete, not `db.delete(candidate)`. The ORM's default relationship
    # cascade tries to *disown* the children first — `UPDATE search_results SET
    # candidate_id = NULL` — which the column's NOT NULL rejects, so the whole
    # deletion fails. Going through Core lets the database apply the
    # `ondelete="CASCADE"` the schema already declares, which removes the rows
    # rather than orphaning them.
    db.expunge(candidate)
    db.execute(
        delete(Candidate)
        .where(Candidate.id == candidate_id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return True


def prune_raw_payloads(db: Session, *, older_than_days: int | None = None) -> int:
    """Drop the stored provider payload from profiles past the freshness window.

    `raw` exists to debug extraction and is the largest column here — a complete
    second copy of everything already parsed into proper fields. Once a profile
    is old enough to be re-fetched rather than reused, it has no further use.
    """
    days = older_than_days if older_than_days is not None else settings.profile_ttl_days
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # synchronize_session=False: otherwise SQLAlchemy evaluates the WHERE in
    # Python to update objects already in the session, and SQLite hands back
    # naive datetimes that cannot be compared with an aware cutoff. Let the
    # database do the comparison it is being given.
    result = db.execute(
        update(Candidate)
        .where(Candidate.fetched_at < cutoff, Candidate.raw.is_not(None))
        .values(raw=None)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount or 0


def purge_orphaned_candidates(db: Session, *, older_than_days: int) -> int:
    """Delete profiles that no search result and no saved list still points at.

    A candidate scraped once, matched to nothing, and never searched again is
    kept indefinitely otherwise. `profile_ttl_days` does not help: it governs
    cache freshness, so an "expired" profile is re-scraped and overwritten,
    never removed.
    """
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

    orphans = select(Candidate.id).where(
        Candidate.fetched_at < cutoff,
        Candidate.id.not_in(select(SearchResult.candidate_id)),
        Candidate.id.not_in(select(SavedCandidate.candidate_id)),
    )
    ids = list(db.scalars(orphans))
    if not ids:
        return 0

    db.execute(
        delete(Candidate)
        .where(Candidate.id.in_(ids))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    logger.warning("orphaned_candidates_purged", count=len(ids), older_than_days=older_than_days)
    return len(ids)


def purge_expired(db: Session) -> dict[str, int]:
    """The routine sweep: prune payloads, then drop unreferenced profiles."""
    pruned = prune_raw_payloads(db)
    purged = purge_orphaned_candidates(db, older_than_days=settings.candidate_retention_days)
    if pruned or purged:
        logger.info("retention_sweep", raw_pruned=pruned, candidates_purged=purged)
    return {"raw_pruned": pruned, "candidates_purged": purged}


def candidate_count(db: Session) -> int:
    return db.scalar(select(func.count(Candidate.id))) or 0

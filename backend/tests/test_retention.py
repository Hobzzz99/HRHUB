"""Candidate data has to be deletable, and must not be kept for ever.

COMPLIANCE.md commits to "a retention policy, and a deletion/DSAR path", to
"add a purge job for production", and to pruning `Candidate.raw`. None of it
existed: the only DELETE in the API removed a *bookmark* and left the profile
untouched, so answering "please delete me" meant hand-written SQL against
production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import Candidate, SavedCandidate, SearchResult
from app.db.session import SessionLocal
from app.schemas.search import SearchCreate
from app.services import retention, search_service
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-0000000000ff"


def _candidate(db, *, age_days: int = 0, raw: dict | None = None) -> Candidate:
    candidate = Candidate(
        source="linkedin",
        source_profile_url=f"https://linkedin.com/in/{uuid.uuid4().hex[:12]}",
        name="Ahmed Sedeik",
        current_title="External Audit Manager",
        raw=raw if raw is not None else {"everything": "the provider returned"},
        fetched_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


class TestForgetCandidate:
    def test_a_candidate_can_be_erased(self):
        db = SessionLocal()
        try:
            candidate = _candidate(db)
            candidate_id = candidate.id
            assert retention.forget_candidate(db, candidate_id) is True
            db.expunge_all()
            assert db.get(Candidate, candidate_id) is None
        finally:
            db.close()

    def test_erasing_takes_every_shortlist_with_it(self):
        """A deletion request must not leave copies on recruiters' lists."""
        db = SessionLocal()
        try:
            ensure_user(db, USER_ID, "dev@example.com")
            db.commit()
            candidate = _candidate(db)
            search = search_service.create_search(
                db, USER_ID, SearchCreate(job_title="external audit manager")
            )
            db.add(SearchResult(search_id=search.id, candidate_id=candidate.id,
                                match_score=90.0, score_version="v4", rank=1))
            db.add(SavedCandidate(user_id=search.user_id, candidate_id=candidate.id))
            db.commit()

            retention.forget_candidate(db, candidate.id)

            assert db.query(SearchResult).filter_by(candidate_id=candidate.id).count() == 0
            assert db.query(SavedCandidate).filter_by(candidate_id=candidate.id).count() == 0
        finally:
            db.close()

    def test_forgetting_someone_absent_is_not_an_error(self):
        db = SessionLocal()
        try:
            assert retention.forget_candidate(db, uuid.uuid4()) is False
        finally:
            db.close()


class TestRawPruning:
    def test_stale_payloads_are_dropped(self):
        """`raw` is a second copy of everything already parsed into columns."""
        db = SessionLocal()
        try:
            old = _candidate(db, age_days=90)
            assert retention.prune_raw_payloads(db, older_than_days=7) >= 1
            db.refresh(old)
            assert old.raw is None
        finally:
            db.close()

    def test_a_fresh_profile_keeps_its_payload(self):
        """Still inside the cache window, so still useful for debugging."""
        db = SessionLocal()
        try:
            fresh = _candidate(db, age_days=1)
            retention.prune_raw_payloads(db, older_than_days=7)
            db.refresh(fresh)
            assert fresh.raw is not None
        finally:
            db.close()


class TestOrphanPurge:
    def test_an_unreferenced_profile_is_deleted(self):
        """Scraped once, matched to nothing, never searched again."""
        db = SessionLocal()
        try:
            orphan = _candidate(db, age_days=400)
            orphan_id = orphan.id
            assert retention.purge_orphaned_candidates(db, older_than_days=180) >= 1
            # Bulk delete bypasses the identity map, so drop the stale instance
            # rather than asking the session to refresh a row that is gone.
            db.expunge_all()
            assert db.get(Candidate, orphan_id) is None
        finally:
            db.close()

    def test_a_profile_on_a_shortlist_is_kept(self):
        """Retention must never delete work a recruiter is still using."""
        db = SessionLocal()
        try:
            ensure_user(db, USER_ID, "dev@example.com")
            db.commit()
            candidate = _candidate(db, age_days=400)
            search = search_service.create_search(
                db, USER_ID, SearchCreate(job_title="external audit manager")
            )
            db.add(SearchResult(search_id=search.id, candidate_id=candidate.id,
                                match_score=90.0, score_version="v4", rank=1))
            db.commit()

            retention.purge_orphaned_candidates(db, older_than_days=180)
            assert db.get(Candidate, candidate.id) is not None
        finally:
            db.close()

    def test_a_saved_profile_is_kept(self):
        db = SessionLocal()
        try:
            ensure_user(db, USER_ID, "dev@example.com")
            db.commit()
            candidate = _candidate(db, age_days=400)
            db.add(SavedCandidate(user_id=uuid.UUID(USER_ID), candidate_id=candidate.id))
            db.commit()

            retention.purge_orphaned_candidates(db, older_than_days=180)
            assert db.get(Candidate, candidate.id) is not None
        finally:
            db.close()

    def test_a_recent_orphan_is_kept(self):
        db = SessionLocal()
        try:
            recent = _candidate(db, age_days=5)
            retention.purge_orphaned_candidates(db, older_than_days=180)
            assert db.get(Candidate, recent.id) is not None
        finally:
            db.close()


class TestCandidateScoping:
    def test_a_candidate_from_another_recruiters_search_is_not_readable(self):
        """`candidates` is deduplicated globally — one row per real person,
        shared by everyone who finds them — so a bare id lookup returned
        anybody's sourcing to anybody holding the id."""
        db = SessionLocal()
        try:
            ensure_user(db, USER_ID, "dev@example.com")
            ensure_user(db, OTHER_USER_ID, "other@example.com")
            db.commit()
            candidate = _candidate(db)
            search = search_service.create_search(
                db, USER_ID, SearchCreate(job_title="external audit manager")
            )
            db.add(SearchResult(search_id=search.id, candidate_id=candidate.id,
                                match_score=90.0, score_version="v4", rank=1))
            db.commit()

            assert search_service.get_candidate(db, USER_ID, candidate.id) is not None
            assert search_service.get_candidate(db, OTHER_USER_ID, candidate.id) is None
        finally:
            db.close()

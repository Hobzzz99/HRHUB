"""The search pipeline: provider search → pre-filter → cache/fetch → score → filter → store.

Runs inside the Celery worker (via ``asyncio.run``). Provider calls are async;
DB and domain calls are synchronous. Progress is committed incrementally so the
SSE status stream reflects live state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import SearchStatus
from app.db.models import Search, SearchResult
from app.domain.filtering import apply_filters
from app.domain.models import ScoredCandidate, SearchCriteria
from app.domain.prefilter import passes_prefilter
from app.domain.scoring import score_candidate
from app.providers.base import CandidateProvider, ProviderError
from app.providers.factory import get_provider
from app.services import candidate_service, provider_account_service, search_service
from app.db.session import SessionLocal, session_scope

logger = get_logger(__name__)


def _set_progress(db: Session, search: Search, **changes) -> None:
    progress = dict(search.progress or {})
    progress.update(changes)
    search.progress = progress
    db.commit()


async def execute_search(search_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        search = db.get(Search, search_id)
        if search is None:
            logger.warning("search_not_found", search_id=str(search_id))
            return

        search.status = SearchStatus.RUNNING
        db.commit()
        criteria = search_service.criteria_from_search(search)

        try:
            await _run_pipeline(db, search, criteria)
            search.status = SearchStatus.COMPLETED
            search.completed_at = datetime.now(timezone.utc)
            search.error = None
        except Exception as exc:  # noqa: BLE001 — record failure, don't crash worker
            logger.exception("search_failed", search_id=str(search_id))
            search.status = SearchStatus.FAILED
            search.error = str(exc)
            search.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _build_provider(db: Session, search: Search) -> CandidateProvider:
    """Build the provider, loading encrypted credentials/session for scraping."""
    if search.provider not in ("playwright", "linkedin"):
        return get_provider(search.provider)

    account = provider_account_service.get_account(db, str(search.user_id), "linkedin")
    credentials = provider_account_service.decrypt_credentials(account)
    session_state = provider_account_service.load_session_state(account)

    async def on_session_update(state: dict) -> None:
        if account is None:
            return
        with session_scope() as s:
            provider_account_service.save_session_state(s, account.id, state)

    return get_provider(
        "playwright",
        credentials=credentials,
        session_state=session_state,
        on_session_update=on_session_update if account else None,
    )


async def _run_pipeline(db: Session, search: Search, criteria: SearchCriteria) -> None:
    provider = _build_provider(db, search)
    kept: list[tuple[uuid.UUID, ScoredCandidate]] = []
    all_scored: list[tuple[uuid.UUID, ScoredCandidate]] = []

    async with provider:
        hits = await provider.search(criteria)

        # Conservative pre-filter on cheap card data.
        survivors = [hit for hit in hits if passes_prefilter(hit, criteria)[0]]
        # Fetch as many as the recruiter asked for (max_results), never exceeding
        # the safety ceiling that caps per-search fetch cost/time. Sizing by
        # max_results also avoids opening profiles we would only discard.
        fetch_limit = min(search.max_results, settings.scrape_max_profiles)
        to_process = survivors[:fetch_limit]
        _set_progress(
            db, search, found=len(hits), to_process=len(to_process), processed=0, kept=0
        )

        processed = 0
        for hit in to_process:
            processed += 1
            try:
                candidate = candidate_service.get_fresh_candidate(
                    db, provider.name, hit.source_profile_url
                )
                if candidate is None:
                    raw = await provider.fetch_profile(hit)
                    candidate = candidate_service.upsert_candidate(db, raw)
                    db.commit()

                profile = candidate_service.candidate_to_raw_profile(candidate)
                scored = score_candidate(
                    profile, criteria, total_years=candidate.total_experience_years
                )
                scored = await _maybe_ai_enhance(scored, profile, criteria)

                all_scored.append((candidate.id, scored))
                decision = apply_filters(profile, scored, criteria)
                if decision.keep:
                    kept.append((candidate.id, scored))
            except ProviderError as exc:
                logger.warning(
                    "profile_skipped", url=hit.source_profile_url, error=str(exc)
                )
            _set_progress(db, search, processed=processed, kept=len(kept))

    # Prefer candidates that passed all filters; but if none did, still return
    # every profile found (ranked, with its match %) so the search is never empty.
    _store_results(db, search, kept or all_scored)


def _store_results(
    db: Session, search: Search, results: list[tuple[uuid.UUID, ScoredCandidate]]
) -> None:
    results.sort(key=lambda item: item[1].match_score, reverse=True)
    for rank, (candidate_id, scored) in enumerate(results[: search.max_results], start=1):
        db.add(
            SearchResult(
                search_id=search.id,
                candidate_id=candidate_id,
                match_score=scored.match_score,
                score_version=scored.score_version,
                score_breakdown=scored.breakdown.model_dump(),
                matched_skills=scored.matched_skills,
                missing_skills=scored.missing_skills,
                reasons=scored.reasons,
                rank=rank,
            )
        )
    db.commit()


async def _maybe_ai_enhance(
    scored: ScoredCandidate, profile, criteria: SearchCriteria
) -> ScoredCandidate:
    if not settings.ai_enabled:
        return scored
    try:
        from app.domain.ai_match import enhance_score

        return await enhance_score(scored, profile, criteria)
    except Exception:  # noqa: BLE001 — AI is best-effort; never break scoring
        logger.warning("ai_enhance_failed", exc_info=True)
        return scored

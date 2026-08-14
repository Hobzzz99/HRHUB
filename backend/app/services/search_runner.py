"""The search pipeline: provider search → pre-filter → cache/fetch → score → filter → store.

Runs inside the Celery worker (via ``asyncio.run``). Provider calls are async;
DB and domain calls are synchronous. Progress is committed incrementally so the
SSE status stream reflects live state.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import ProviderAccountStatus, SearchStatus
from app.db.models import Search, SearchResult
from app.db.session import SessionLocal, session_scope
from app.domain.filtering import apply_filters
from app.domain.models import ScoredCandidate, SearchCriteria
from app.domain.prefilter import passes_prefilter
from app.domain.scoring import score_candidate
from app.providers.base import AccountRestrictedError, CandidateProvider, ProviderError
from app.providers.factory import (
    SCRAPING_PLATFORM,
    SCRAPING_PROVIDERS,
    get_provider,
)
from app.providers.rate_limit import RateLimitExceeded
from app.services import candidate_service, provider_account_service, search_service

logger = get_logger(__name__)

#: Give up when this many profiles in a row fail for reasons we did not expect
#: and nothing has been kept. Past this point the run is almost certainly broken
#: (session gone, network down, layout changed) and continuing only spends
#: scrape budget that takes an hour to come back.
_CONSECUTIVE_FAILURE_LIMIT = 3


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
            search.completed_at = datetime.now(UTC)
            search.error = None
        except AccountRestrictedError as exc:
            # The one place a restriction is recorded, so every route into it —
            # refused up front, hit during the provider search, or hit part-way
            # through the profile loop — retires the account exactly once.
            logger.warning("search_stopped_account_restricted", search_id=str(search_id))
            provider_account_service.mark_restricted(
                db, str(search.user_id), SCRAPING_PLATFORM.get(search.provider, "linkedin")
            )
            search.status = SearchStatus.FAILED
            search.error = str(exc)
            search.completed_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 — record failure, don't crash worker
            logger.exception("search_failed", search_id=str(search_id))
            search.status = SearchStatus.FAILED
            search.error = str(exc)
            search.completed_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()


def _build_provider(db: Session, search: Search) -> CandidateProvider:
    """Build the provider, restoring the encrypted browser session for scraping."""
    if search.provider not in SCRAPING_PROVIDERS:
        return get_provider(search.provider)

    platform = SCRAPING_PLATFORM[search.provider]
    # Created on demand: sign-in is manual, so nothing else would ever create
    # the row, and without it every search would demand a fresh login.
    account = provider_account_service.get_or_create_live_account(
        db, str(search.user_id), platform
    )
    if account.status == ProviderAccountStatus.RESTRICTED:
        # Refuse rather than silently starting a fresh account: rotating is the
        # operator's decision, and it needs them to sign in as somebody else.
        raise AccountRestrictedError(
            f"This {platform} account is marked restricted, so the search was "
            "not started. Connect a different account in Settings to continue, "
            "or run the search against a different data source."
        )
    session_state = provider_account_service.load_session_state(account)
    account_id = account.id

    async def on_session_update(state: dict) -> None:
        with session_scope() as s:
            provider_account_service.save_session_state(s, account_id, state)

    return get_provider(
        search.provider,
        session_state=session_state,
        on_session_update=on_session_update,
        # The account row's id seeds the browser fingerprint, so this account
        # keeps one machine identity for its whole life and a different account
        # gets different hardware. Deleting the row to switch accounts therefore
        # rotates the fingerprint too, which is exactly what you want when the
        # previous account was restricted.
        fingerprint_seed=str(account_id),
    )


def _budget_progress(provider: CandidateProvider) -> dict:
    """Remaining hourly scrape budget, for providers that have one.

    Reported up front so a search that is about to stall on the rate limit says
    so before it starts, rather than looking hung.
    """
    budget = getattr(provider, "budget", None)
    if budget is None:
        return {}
    snapshot = budget()
    return {
        "budget_used": snapshot.used,
        "budget_limit": snapshot.limit,
        "budget_remaining": snapshot.remaining,
    }


class _Collection:
    """Everything a run accumulates, so a failure can still be reported on."""

    def __init__(self) -> None:
        self.kept: list[tuple[uuid.UUID, ScoredCandidate]] = []
        self.all_scored: list[tuple[uuid.UUID, ScoredCandidate]] = []
        self.failures: list[str] = []
        self.processed = 0
        self.restricted: AccountRestrictedError | None = None


async def _score_one(
    db: Session,
    provider: CandidateProvider,
    hit,
    criteria: SearchCriteria,
    run: _Collection,
) -> None:
    """Fetch (or reuse) one profile, score it, and record whether it survives."""
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

    run.all_scored.append((candidate.id, scored))
    if apply_filters(profile, scored, criteria).keep:
        run.kept.append((candidate.id, scored))


async def _collect(
    db: Session,
    search: Search,
    criteria: SearchCriteria,
    provider: CandidateProvider,
    run: _Collection,
    started: float,
) -> None:
    """Search, then open and score profiles until done or stopped."""
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
            db,
            search,
            found=len(hits),
            to_process=len(to_process),
            processed=0,
            kept=0,
            search_seconds=round(time.monotonic() - started, 1),
            **_budget_progress(provider),
        )

        for hit in to_process:
            run.processed += 1
            try:
                await _score_one(db, provider, hit, criteria, run)
            except RateLimitExceeded as exc:
                # The hourly scrape budget is spent. Stop cleanly and keep what
                # we already have — a partial result set is far more useful than
                # a failed search, and the recruiter can re-run it later to pick
                # up where this left off (cached profiles are not re-fetched).
                logger.info("search_stopped_at_rate_limit", search_id=str(search.id))
                _set_progress(
                    db,
                    search,
                    processed=run.processed - 1,
                    kept=len(run.kept),
                    rate_limited=True,
                    retry_after_s=int(exc.retry_after_s),
                    note=str(exc),
                )
                return
            except AccountRestrictedError as exc:
                # Terminal, and every further profile would hit the same locked
                # account — which is what turns a restriction permanent. Stop
                # here; the caller re-raises once results are safely stored.
                run.restricted = exc
                _set_progress(
                    db,
                    search,
                    processed=run.processed - 1,
                    kept=len(run.kept),
                    account_restricted=True,
                    note=str(exc),
                )
                return
            except ProviderError as exc:
                logger.warning(
                    "profile_skipped", url=hit.source_profile_url, error=str(exc)
                )
            except Exception as exc:  # noqa: BLE001 — reason below
                # Anything the provider did not translate: navigation timeouts,
                # aborted requests, a page that vanished mid-read. These are the
                # ordinary weather of driving someone else's site and they are
                # per-profile problems, so one must not end the run.
                logger.warning(
                    "profile_failed_unexpectedly",
                    url=hit.source_profile_url,
                    error=str(exc),
                    exc_info=True,
                )
                run.failures.append(str(exc))
                if len(run.failures) >= _CONSECUTIVE_FAILURE_LIMIT and not run.kept:
                    # Nothing is working. Stop rather than spend the rest of an
                    # hourly budget repeating one failure against every profile.
                    logger.error("search_abandoned_after_repeated_failures")
                    _set_progress(
                        db,
                        search,
                        processed=run.processed,
                        kept=0,
                        note=f"Stopped after {len(run.failures)} profiles failed to load.",
                    )
                    return
            _set_progress(
                db,
                search,
                processed=run.processed,
                kept=len(run.kept),
                elapsed_seconds=round(time.monotonic() - started, 1),
            )


async def _run_pipeline(db: Session, search: Search, criteria: SearchCriteria) -> None:
    # Wall-clock, because that is the number the recruiter experiences: it
    # includes the browser waiting on LinkedIn, not just our own work.
    started = time.monotonic()
    provider = _build_provider(db, search)
    run = _Collection()

    # Everything a scraped profile costs — minutes of wall-clock and a slice of
    # an hourly budget that cannot be reclaimed — is spent before this returns.
    # So whatever happens, what was collected gets stored: a failure costs the
    # recruiter the remainder of the run rather than all of it.
    try:
        await _collect(db, search, criteria, provider, run, started)
    finally:
        stored = _results_to_store(criteria, run.kept, run.all_scored)
        _store_results(db, search, stored)

        elapsed = time.monotonic() - started
        _set_progress(
            db,
            search,
            elapsed_seconds=round(elapsed, 1),
            seconds_per_profile=(
                round(elapsed / run.processed, 1) if run.processed else None
            ),
            returned=len(stored[: search.max_results]),
            failed_profiles=len(run.failures) or None,
        )
        logger.info(
            "search_timing",
            search_id=str(search.id),
            elapsed_s=round(elapsed, 1),
            profiles=run.processed,
            returned=len(stored[: search.max_results]),
            failed=len(run.failures),
        )

    # Raised only after the partial results are committed: a restriction should
    # cost the operator the rest of the run, not the profiles already paid for.
    if run.restricted is not None:
        raise run.restricted


def _has_hard_requirements(criteria: SearchCriteria) -> bool:
    """Did the recruiter state a requirement they expect to be enforced?"""
    return bool(
        criteria.critical_skills
        or criteria.min_match_score > 0
        or criteria.min_experience > 0
        or criteria.graduation_year_from is not None
        or criteria.graduation_year_to is not None
        or criteria.companies
        or (criteria.enforce_location and criteria.location)
    )


def _results_to_store(
    criteria: SearchCriteria,
    kept: list[tuple[uuid.UUID, ScoredCandidate]],
    all_scored: list[tuple[uuid.UUID, ScoredCandidate]],
) -> list[tuple[uuid.UUID, ScoredCandidate]]:
    """Which candidates the search should return.

    Normally the ones that passed every filter. When *nothing* passed there is a
    judgement call, and it turns on whether the recruiter actually stated a
    requirement:

    * They did — return nothing. Showing rejected candidates anyway silently
      overrides the filters they set, which reads as the filtering being broken
      and, worse, puts people in front of them who fail a stated requirement.
    * They did not — return everything, ranked. With no requirements to fail,
      an empty page would only mean "the source found nobody useful", and a
      ranked list of near-misses is more informative than a blank screen.
    """
    if kept:
        return kept
    return [] if _has_hard_requirements(criteria) else all_scored


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
                matched_keywords=scored.matched_keywords,
                missing_keywords=scored.missing_keywords,
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

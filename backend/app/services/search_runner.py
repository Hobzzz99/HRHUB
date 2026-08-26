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
from app.providers.base import (
    AccountRestrictedError,
    CandidateProvider,
    Degradation,
    ProviderError,
)
from app.providers.factory import (
    SCRAPING_PLATFORM,
    SCRAPING_PROVIDERS,
    get_provider,
)
from app.providers.rate_limit import RateLimitExceeded
from app.services import candidate_service, provider_account_service, search_service

logger = get_logger(__name__)

#: Give up when this many profiles **in a row** fail. Past this point the run is
#: almost certainly broken (session gone, network down, layout changed) and
#: continuing only spends scrape budget that takes an hour to come back.
#:
#: Genuinely consecutive: the counter resets on every profile that works. The
#: previous version compared a cumulative total and only fired while nothing had
#: been kept, so a single successful profile disabled the brake for the rest of
#: the run — and a session that expired at profile two spent the other eighteen
#: slots failing, then reported the search as completed with no results.
_CONSECUTIVE_FAILURE_LIMIT = 3

#: Rejection reasons carry one candidate's particulars — "Only 3 yrs experience",
#: "Works at AMSG, not Deloitte / PwC" — so grouping the raw strings gives every
#: candidate their own bucket and tells the recruiter nothing. These map each
#: reason to the shape of the complaint.
#:
#: A table rather than a regex because the reasons all come from one module
#: (`domain/filtering.py`) and are known: guessing at their structure produced
#: "2x Works", which is worse than not summarising at all. An unrecognised
#: reason keeps its own text, so a new filter degrades to verbose, never wrong.
_REJECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("Only ", "not enough experience"),
    ("Missing critical skills", "missing a required qualification"),
    ("Works at ", "works at a different employer"),
    ("No experience in", "no evidence of this line of work"),
    ("Score ", "scored below your threshold"),
    ("Location does not match", "outside the requested location"),
    ("Graduated ", "outside the graduation-year window"),
)


def _rejection_label(reason: str) -> str:
    for prefix, label in _REJECTION_LABELS:
        if reason.startswith(prefix):
            return label
    return reason.strip()


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
            cancelled = await _run_pipeline(db, search, criteria)
            search.status = (
                SearchStatus.CANCELLED if cancelled else SearchStatus.COMPLETED
            )
            search.completed_at = datetime.now(UTC)
            # Cancelling is not an error, so `error` stays empty — the note in
            # progress explains it, and the results collected so far are shown.
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
        #: Reset by every profile that works, so the brake measures a run that
        #: has stopped working rather than one that has ever failed.
        self.consecutive_failures = 0
        self.processed = 0
        self.restricted: AccountRestrictedError | None = None
        #: The recruiter stopped it. Not a failure, and the partial results stand.
        self.cancelled = False
        #: Reasons the results answer a different question than the one asked.
        self.degradations: list[tuple[str, str]] = []
        #: Why filtered-out candidates were filtered out, so an empty shortlist
        #: can explain itself.
        self.rejections: list[str] = []


def _record_failure(db: Session, search: Search, run: _Collection, error: str) -> bool:
    """Note a profile that could not be read. True when the run should stop.

    Every failure here has already cost a slot of an hourly budget that takes an
    hour to refill, so the point of stopping is not tidiness — it is to leave the
    recruiter something to re-run with.
    """
    run.failures.append(error)
    run.consecutive_failures += 1
    if run.consecutive_failures < _CONSECUTIVE_FAILURE_LIMIT:
        return False

    logger.error(
        "search_abandoned_after_repeated_failures",
        consecutive=run.consecutive_failures,
        kept=len(run.kept),
    )
    run.degradations.append(
        (
            Degradation.PROFILES_UNREACHABLE.value,
            f"{run.consecutive_failures} profiles in a row could not be opened, so "
            "the search stopped early. This is a problem reading LinkedIn, not "
            "your criteria.",
        )
    )
    _set_progress(
        db,
        search,
        processed=run.processed,
        kept=len(run.kept),
        failed_profiles=len(run.failures),
        note=f"Stopped after {run.consecutive_failures} profiles in a row failed to load.",
    )
    return True


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

    # This profile worked, so the run is not stuck. Reset before recording the
    # outcome: a candidate the filters reject is still a profile we read fine.
    run.consecutive_failures = 0

    run.all_scored.append((candidate.id, scored))
    decision = apply_filters(profile, scored, criteria)
    if decision.keep:
        run.kept.append((candidate.id, scored))
    else:
        # Kept so the recruiter can be told *why* nobody survived. Without this
        # the only record of "8 rejected for employer, 2 for the credential" is
        # discarded, and an over-tight search is indistinguishable from a broken
        # scraper.
        run.rejections.extend(decision.reasons)


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
            # Between profiles, never mid-profile: this profile has already been
            # charged to the hourly budget, so abandoning it now would waste a
            # slot that takes an hour to come back.
            db.refresh(search)
            if search.cancel_requested:
                logger.info("search_cancelled_by_user", search_id=str(search.id))
                run.cancelled = True
                _set_progress(
                    db,
                    search,
                    processed=run.processed,
                    kept=len(run.kept),
                    note="Cancelled. Everything collected before you stopped it is kept.",
                )
                return

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
                # A profile we could not open or read. Skipping one is ordinary;
                # skipping several in a row is systemic — an expired session, a
                # layout change — and each one has *already* spent a budget slot
                # before failing. This used to be logged and forgotten, which is
                # how a session that expired mid-run burned the remaining budget
                # and still reported the search as completed.
                logger.warning(
                    "profile_skipped", url=hit.source_profile_url, error=str(exc)
                )
                if _record_failure(db, search, run, str(exc)):
                    return
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
                if _record_failure(db, search, run, str(exc)):
                    return
            _set_progress(
                db,
                search,
                processed=run.processed,
                kept=len(run.kept),
                elapsed_seconds=round(time.monotonic() - started, 1),
            )


async def _run_pipeline(db: Session, search: Search, criteria: SearchCriteria) -> bool:
    """Run the search. Returns True when the recruiter stopped it part-way."""
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
        # Whatever the provider could not do, collected even on the failure path
        # — a run that died half-way still has to explain what it managed.
        run.degradations.extend(
            (kind.value, detail) for kind, detail in provider.degradations
        )
        stored = _results_to_store(criteria, run.kept, run.all_scored)
        _store_results(db, search, stored)
        search.degraded_reasons = [
            {"kind": kind, "detail": detail} for kind, detail in run.degradations
        ] or None

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
            rejected=len(run.all_scored) - len(run.kept) or None,
            rejection_reasons=_top_rejections(run.rejections),
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

    return run.cancelled


def _top_rejections(reasons: list[str], limit: int = 4) -> list[str] | None:
    """The commonest reasons candidates were filtered out, most frequent first.

    This is what turns "No candidates matched" into "8 works at a different
    employer, 2 missing a required qualification" — the difference between a
    recruiter guessing at their criteria and knowing which one to loosen.
    """
    if not reasons:
        return None

    counts: dict[str, int] = {}
    for reason in reasons:
        label = _rejection_label(reason)
        counts[label] = counts.get(label, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [f"{count}x {label}" for label, count in ranked]


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

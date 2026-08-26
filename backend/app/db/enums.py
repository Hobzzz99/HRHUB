"""Enumerations used across the domain and persistence layers.

Stored as short strings (not native DB enums) to keep migrations simple and
tests portable across Postgres/SQLite.
"""

from __future__ import annotations

from enum import StrEnum


class SearchStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    #: Stopped on purpose by the recruiter. Distinct from FAILED: nothing went
    #: wrong, and whatever had been collected is kept and shown.
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            SearchStatus.COMPLETED,
            SearchStatus.FAILED,
            SearchStatus.CANCELLED,
        )


class CandidateSource(StrEnum):
    """Where a candidate profile came from. LinkedIn is just one of many."""

    MOCK = "mock"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    PROXYCURL = "proxycurl"
    PEOPLE_DATA_LABS = "people_data_labs"


class ProviderAccountStatus(StrEnum):
    """Lifecycle of a connected provider account.

    A user has at most one *live* row per provider (active or restricted) plus
    any number of retired ones. Retired rows are never deleted: the row id seeds
    the browser fingerprint, so keeping them is what guarantees a replacement
    account never presents the same machine as the account it replaced.
    """

    ACTIVE = "active"
    #: The platform locked the account. Terminal — searches refuse to run on it
    #: until the operator rotates to a different account.
    RESTRICTED = "restricted"
    #: Superseded by a rotation. Kept only so its id is never reused.
    RETIRED = "retired"

    @property
    def is_live(self) -> bool:
        """True for the one row that currently represents this provider."""
        return self is not ProviderAccountStatus.RETIRED

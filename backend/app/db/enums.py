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

    @property
    def is_terminal(self) -> bool:
        return self in (SearchStatus.COMPLETED, SearchStatus.FAILED)


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
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALID = "invalid"

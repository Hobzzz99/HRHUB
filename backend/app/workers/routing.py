"""Which machine runs a given search.

With one shared worker this file would not need to exist. It exists because
each recruiter scrapes with **their own LinkedIn account, signed in by hand on
their own laptop** — so a search is not work that any worker may pick up. It
belongs to exactly one machine.

Celery's default is the opposite: every worker consumes the same queue and jobs
go to whoever is free. Under that default, a search started by one recruiter
gets collected by a colleague's laptop, which then loads the *originating*
recruiter's LinkedIn session — because sessions are stored per user — into a
different browser, on a different IP, in front of somebody who cannot complete
the sign-in prompt if one appears.

That is not just a confusing failure. Reusing a session across machines and
addresses is close to the textbook signal of a compromised account, and it is
the behaviour most likely to get the account restricted.

So each recruiter's worker listens only to its own queue.
"""

from __future__ import annotations

#: Queue every worker can serve, for work that touches no personal account.
SHARED_QUEUE = "celery"

_USER_QUEUE_PREFIX = "user-"


def user_queue(user_id: str) -> str:
    """The queue served only by this user's own machine."""
    return f"{_USER_QUEUE_PREFIX}{user_id}"

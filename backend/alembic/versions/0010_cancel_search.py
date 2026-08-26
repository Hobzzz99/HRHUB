"""searches.cancel_requested — let a recruiter stop a search they did not mean to start

Enter submits the form, so a half-filled search starts on a misclick and then
spends real scrape budget against a real LinkedIn account for several minutes.
There was no way to stop it.

A column rather than a Celery revoke: the worker runs on the recruiter's own
laptop, not on the server, and it already re-reads its search row between
profiles to write progress. Revoking would also kill the process mid-profile and
lose the work it had already paid for.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "searches",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("searches", "cancel_requested")

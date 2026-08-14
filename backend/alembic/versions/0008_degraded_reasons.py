"""searches.degraded_reasons — what a run could not do, when it still returned results

Until now a search had two outcomes: it finished, or it raised. A run whose Big
Four filter never reached LinkedIn, or that gave up after every profile failed to
open, finished — and the recruiter was shown "No candidates matched. Try lowering
the minimum score", which blames them for a broken scraper.

This column carries the difference. `error` still means the run did not finish;
this means it finished but answers a different question than the one asked.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no default: a null means "nothing was degraded", which is
    # also the correct reading for every row that predates this column.
    op.add_column("searches", sa.Column("degraded_reasons", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("searches", "degraded_reasons")

"""searches.graduation_year_from / _to — filter by career stage

Recruiters describe early-career hiring as a graduation-year range, because that
is the figure printed on a profile. Tested against the candidate's earliest
graduation, so a recent part-time qualification does not make a long career read
as a new one.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("searches", sa.Column("graduation_year_from", sa.Integer(), nullable=True))
    op.add_column("searches", sa.Column("graduation_year_to", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("searches", schema=None) as batch:
        batch.drop_column("graduation_year_to")
        batch.drop_column("graduation_year_from")

"""searches.require_title_match — discard candidates outside the role's field

A search for "external audit manager" was returning finance managers: the only
word they shared was "manager", which every management title contains. Scoring
alone could not fix that, because experience and location still carried them.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "searches",
        sa.Column("require_title_match", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    with op.batch_alter_table("searches", schema=None) as batch:
        batch.drop_column("require_title_match")

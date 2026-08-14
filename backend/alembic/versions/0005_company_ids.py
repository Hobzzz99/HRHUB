"""searches.company_ids — LinkedIn company ids pasted from a search URL

Names have to be resolved through LinkedIn's filter panel, and an id belongs to
a specific legal entity ("KPMG" and "KPMG Middle East" are different pages with
different ids). Letting a recruiter paste a search URL they already built skips
the resolution entirely and cannot pick the wrong entity.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("searches", sa.Column("company_ids", sa.JSON(), nullable=True))
    op.execute("UPDATE searches SET company_ids = '[]' WHERE company_ids IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("searches", schema=None) as batch:
        batch.drop_column("company_ids")

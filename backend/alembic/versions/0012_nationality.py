"""searches.nationality — filter on likely citizenship, judged from where they studied

LinkedIn has no nationality field. What a profile carries is the university,
which for a country whose graduates overwhelmingly hold its citizenship is real
evidence — and it is the distinction a recruiter in the Gulf actually needs,
because audit practices there are staffed heavily by expatriates and "works in
Riyadh" says nothing about citizenship.

Deliberately not inferred from names: unreliable in both directions, and in
recruiting the textbook route to a discrimination claim.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("searches", sa.Column("nationality", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("searches", "nationality")

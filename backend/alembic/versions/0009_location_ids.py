"""searches.location_ids — LinkedIn geo ids pasted from a search URL

The paste-a-URL escape hatch read only `currentCompany` and silently dropped
`geoUrn`. A recruiter who filtered by both firm and country on LinkedIn and
pasted the result got their companies applied and their location thrown away —
the app then tried to drive the location panel itself, failed, and returned
people from everywhere.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "searches",
        sa.Column("location_ids", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("searches", "location_ids")

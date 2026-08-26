"""searches.experience_in_field — measure the experience bar against the field

"Ten years of external audit" and "ten years of anything, by someone who once
audited" are different requirements, and only the second was being measured.
Across the real profile archive, 105 candidates cleared a ten-year bar on total
career; 28 had ten years of external audit. Among the 77 the old reading let
through: a CEO with thirty-five years and none of them audit, and an internal
audit manager with twenty years of the wrong kind of audit.

Defaults to true because it is what a recruiter means. The switch exists for the
genuinely different question — "anyone senior enough, whatever they did" — which
is a real search, just not the usual one.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "searches",
        sa.Column(
            "experience_in_field",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("searches", "experience_in_field")

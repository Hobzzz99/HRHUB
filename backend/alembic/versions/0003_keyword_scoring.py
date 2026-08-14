"""scoring v2: matched/missing skills become keywords

The v2 weighting is title 30 / keywords 30 / experience 30 / location 10, with
the education component dropped. Scoring now matches the recruiter's keywords
against the candidate's headline and job titles rather than their listed skills,
so the two result columns are renamed to say what they now hold.

`searches.skills` is deliberately left in place: nothing reads it any more, but
historical searches should still show what was originally typed.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMES = (
    ("matched_skills", "matched_keywords"),
    ("missing_skills", "missing_keywords"),
)


def upgrade() -> None:
    # Batch mode so SQLite, which cannot rename a column in place on older
    # versions, gets the same migration path as Postgres.
    with op.batch_alter_table("search_results", schema=None) as batch:
        for old, new in _RENAMES:
            batch.alter_column(old, new_column_name=new)


def downgrade() -> None:
    with op.batch_alter_table("search_results", schema=None) as batch:
        for old, new in _RENAMES:
            batch.alter_column(new, new_column_name=old)

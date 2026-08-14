"""searches.company (one name) becomes searches.companies (a list)

A recruiter filtering on "the Big Four" needs four employers, not one. The
column also now backs LinkedIn's `currentCompany` search facet, which takes a
set of company ids.

Existing single values are carried across as one-element lists so historical
searches keep showing what was asked for.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("searches", sa.Column("companies", sa.JSON(), nullable=True))

    rows = op.get_bind().execute(
        sa.text("SELECT id, company FROM searches WHERE company IS NOT NULL AND company != ''")
    ).fetchall()
    for row_id, company in rows:
        op.get_bind().execute(
            sa.text("UPDATE searches SET companies = :val WHERE id = :id"),
            {"val": json.dumps([company]), "id": row_id},
        )
    op.get_bind().execute(
        sa.text("UPDATE searches SET companies = '[]' WHERE companies IS NULL")
    )

    with op.batch_alter_table("searches", schema=None) as batch:
        batch.drop_column("company")


def downgrade() -> None:
    op.add_column("searches", sa.Column("company", sa.String(length=255), nullable=True))

    rows = op.get_bind().execute(
        sa.text("SELECT id, companies FROM searches WHERE companies IS NOT NULL")
    ).fetchall()
    for row_id, companies in rows:
        try:
            names = json.loads(companies) if isinstance(companies, str) else companies
        except (TypeError, ValueError):
            names = []
        if names:
            # The old column held one name; keep the first and lose the rest.
            op.get_bind().execute(
                sa.text("UPDATE searches SET company = :val WHERE id = :id"),
                {"val": names[0], "id": row_id},
            )

    with op.batch_alter_table("searches", schema=None) as batch:
        batch.drop_column("companies")

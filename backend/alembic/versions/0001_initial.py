"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-17
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )

    op.create_table(
        "provider_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("encrypted_session_state", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_provider_accounts_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_accounts"),
        sa.UniqueConstraint("user_id", "provider", name="uq_provider_accounts_user_id"),
    )
    op.create_index(
        "ix_provider_accounts_user_id", "provider_accounts", ["user_id"]
    )

    op.create_table(
        "searches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("min_experience", sa.Float(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("max_results", sa.Integer(), nullable=True),
        sa.Column("min_match_score", sa.Float(), nullable=True),
        sa.Column("critical_skills", sa.JSON(), nullable=True),
        sa.Column("enforce_location", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("score_version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_searches_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_searches"),
    )
    op.create_index("ix_searches_user_id", "searches", ["user_id"])
    op.create_index("ix_searches_status", "searches", ["status"])
    op.create_index("ix_searches_user_created", "searches", ["user_id", "created_at"])

    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("source_profile_url", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("headline", sa.String(length=512), nullable=True),
        sa.Column("current_title", sa.String(length=255), nullable=True),
        sa.Column("current_company", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("experience", sa.JSON(), nullable=True),
        sa.Column("education", sa.JSON(), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("licenses", sa.JSON(), nullable=True),
        sa.Column("certifications", sa.JSON(), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("total_experience_years", sa.Float(), nullable=True),
        sa.Column("profile_picture_url", sa.String(length=1024), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidates"),
        sa.UniqueConstraint(
            "source", "source_profile_url", name="uq_candidates_source_url"
        ),
    )
    op.create_index("ix_candidates_fetched_at", "candidates", ["fetched_at"])

    op.create_table(
        "search_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("score_version", sa.String(length=16), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=True),
        sa.Column("matched_skills", sa.JSON(), nullable=True),
        sa.Column("missing_skills", sa.JSON(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search_id"], ["searches.id"], name="fk_search_results_search_id_searches",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"],
            name="fk_search_results_candidate_id_candidates", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_search_results"),
        sa.UniqueConstraint(
            "search_id", "candidate_id", name="uq_search_results_search_candidate"
        ),
    )
    op.create_index("ix_search_results_search_id", "search_results", ["search_id"])
    op.create_index("ix_search_results_candidate_id", "search_results", ["candidate_id"])
    op.create_index("ix_search_results_match_score", "search_results", ["match_score"])

    op.create_table(
        "saved_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_saved_candidates_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"],
            name="fk_saved_candidates_candidate_id_candidates", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_saved_candidates"),
        sa.UniqueConstraint(
            "user_id", "candidate_id", name="uq_saved_candidates_user_candidate"
        ),
    )
    op.create_index("ix_saved_candidates_user_id", "saved_candidates", ["user_id"])


def downgrade() -> None:
    op.drop_table("saved_candidates")
    op.drop_table("search_results")
    op.drop_table("candidates")
    op.drop_table("searches")
    op.drop_table("provider_accounts")
    op.drop_table("users")

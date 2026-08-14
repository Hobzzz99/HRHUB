"""provider account rotation: account history, status reason, no credentials

Lets a user retire a locked account and sign in with a different one. Three
changes to `provider_accounts`:

* Replace the ``(user_id, provider)`` unique constraint with a partial unique
  index that only covers non-retired rows, so retired accounts accumulate but
  exactly one stays live. Keeping retired rows is what stops a replacement
  account reusing a burned account's id — and the id seeds the browser
  fingerprint.
* Add ``status_reason`` to record why an account stopped being usable.
* Drop ``encrypted_credentials``. Sign-in is manual, nothing has written this
  column since the credential endpoint was removed, and a column that can hold
  a LinkedIn password is worth deleting rather than leaving empty.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = "status <> 'retired'"


def upgrade() -> None:
    # Batch mode so SQLite (which cannot drop a constraint or column in place)
    # gets the same migration as Postgres.
    with op.batch_alter_table("provider_accounts", schema=None) as batch:
        batch.add_column(sa.Column("status_reason", sa.Text(), nullable=True))
        batch.drop_constraint("uq_provider_accounts_user_id", type_="unique")
        batch.drop_column("encrypted_credentials")

    op.create_index(
        "uq_provider_accounts_live",
        "provider_accounts",
        ["user_id", "provider"],
        unique=True,
        sqlite_where=sa.text(_LIVE),
        postgresql_where=sa.text(_LIVE),
    )


def downgrade() -> None:
    op.drop_index("uq_provider_accounts_live", table_name="provider_accounts")

    # The old unique constraint cannot coexist with retired rows, so collapse
    # the history first, newest kept. Retiring is one-way by design; this only
    # exists so the migration is reversible.
    op.execute(
        """
        DELETE FROM provider_accounts
        WHERE status = 'retired'
        """
    )

    with op.batch_alter_table("provider_accounts", schema=None) as batch:
        batch.add_column(sa.Column("encrypted_credentials", sa.Text(), nullable=True))
        batch.create_unique_constraint(
            "uq_provider_accounts_user_id", ["user_id", "provider"]
        )
        batch.drop_column("status_reason")

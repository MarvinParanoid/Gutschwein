"""members invited from the console have no telegram id

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot alter a column in place; batch mode rebuilds the table.
    # The unique index stays: SQLite and Postgres both allow several NULLs in one.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("telegram_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    # Members without a Telegram id cannot survive the column becoming NOT NULL.
    op.execute("DELETE FROM users WHERE telegram_id IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("telegram_id", existing_type=sa.BigInteger(), nullable=False)

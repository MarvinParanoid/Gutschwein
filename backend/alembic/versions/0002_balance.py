"""remaining balance for amount vouchers

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vouchers", sa.Column("balance_amount", sa.Numeric(precision=10, scale=2))
    )
    # Existing gift cards are assumed untouched: balance starts at face value.
    op.execute(
        "UPDATE vouchers SET balance_amount = value_amount "
        "WHERE value_kind = 'amount' AND value_amount IS NOT NULL "
        "AND status IN ('draft', 'active')"
    )


def downgrade() -> None:
    op.drop_column("vouchers", "balance_amount")

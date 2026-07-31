"""one spelling per currency

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Statistics groups by this string, so ' eur' and 'EUR' would be two currencies
    # with two sets of totals. The field was free text until now; new values are
    # checked, and the ones already saved are brought to the same shape here.
    op.execute("UPDATE vouchers SET currency = upper(trim(currency))")
    op.execute("UPDATE vouchers SET currency = 'EUR' WHERE currency = ''")


def downgrade() -> None:
    # Nothing to undo: the old column accepted these values too.
    pass

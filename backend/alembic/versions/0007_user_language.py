"""per-member language for bot messages

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(length=8), nullable=False, server_default="ru"),
    )


def downgrade() -> None:
    op.drop_column("users", "language")

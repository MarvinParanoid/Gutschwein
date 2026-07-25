"""browser sessions and one-time login tokens

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(f"ix_{name}_token_hash", name, ["token_hash"], unique=True)


def upgrade() -> None:
    _table("login_tokens")
    op.add_column("login_tokens", sa.Column("used_at", sa.DateTime(timezone=True)))
    _table("sessions")
    op.add_column("sessions", sa.Column("last_used_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("login_tokens")

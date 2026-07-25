"""barcode symbology decoded from the image

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vouchers", sa.Column("barcode_format", sa.String(length=32)))


def downgrade() -> None:
    op.drop_column("vouchers", "barcode_format")

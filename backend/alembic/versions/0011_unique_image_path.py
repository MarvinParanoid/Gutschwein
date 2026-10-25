"""one voucher per stored picture

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

INDEX = "ix_vouchers_image_path"


def upgrade() -> None:
    # The app already refuses a second owner (routers.vouchers._claim_image); this
    # makes the database refuse it too. A picture shared by two cards from before
    # that check would make CREATE UNIQUE INDEX fail with a bare constraint error,
    # so they are looked for first and named. Nothing is changed to make it pass:
    # which card keeps the picture is a person's decision, not a migration's.
    shared = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT image_path, group_concat(id, ', ') AS vouchers FROM vouchers "
                "WHERE image_path IS NOT NULL GROUP BY image_path HAVING count(*) > 1 "
                "ORDER BY image_path"
            )
        )
        .all()
    )
    if shared:
        raise RuntimeError(_shared_pictures_message(shared))
    # A plain CREATE INDEX: no table rebuild. NULLs are distinct in a unique index,
    # so any number of cards without a picture is fine.
    op.create_index(INDEX, "vouchers", ["image_path"], unique=True)


def _shared_pictures_message(shared) -> str:
    """What to do, written for someone whose app will not start until this passes.

    The app cannot be used to fix it (it migrates before it serves), and an older
    image cannot run on this schema either — so the message carries the fix: keep
    the picture on one card per group, detach it from the others, start again, and
    upload their screenshots anew in the app.
    """
    groups, detach = [], []
    for row in shared:
        ids = [int(i) for i in row.vouchers.split(", ")]
        groups.append(f"{row.image_path}: vouchers {', '.join(map(str, ids))}")
        detach.extend(ids[1:])
    sql = (
        "UPDATE vouchers SET image_path = NULL, barcode_format = NULL "
        f"WHERE id IN ({', '.join(map(str, detach))})"
    )
    return (
        f"cannot make pictures unique: {len(shared)} picture(s) are attached to more than "
        f"one voucher — {'; '.join(groups)}. This migration changed nothing, and the app "
        "will not start until it can run. Decide which card each picture belongs to "
        "(the one whose code it shows), then detach it from the others. To keep it on "
        "the lowest id of each group:\n"
        f'  docker compose run --rm app python -c "import sqlite3; '
        f"c = sqlite3.connect('/data/gutschwein.db'); c.execute('{sql}'); c.commit()\"\n"
        "then start the app again and upload the detached cards' screenshots in it."
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="vouchers")

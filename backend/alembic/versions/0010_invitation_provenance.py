"""where a member without Telegram gets their access from

Revision ID: 0010
Revises: 0009
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# Every column that points at a member. A pointer to a row that is gone means a
# member was deleted at some point, and nobody can say any more what kind they were.
MEMBER_REFERENCES = (
    ("vouchers", "created_by_id"),
    ("vouchers", "used_by_id"),
    ("comments", "author_id"),
    ("events", "actor_id"),
    ("sessions", "user_id"),
    ("login_tokens", "user_id"),
)


def upgrade() -> None:
    # Plain ADD COLUMN, no batch rebuild: the table is not copied, so nothing that
    # references it (sessions, history) is touched. Invariants between the three
    # are checked by app.membership on every request instead of a CHECK, which
    # SQLite can only add by rebuilding the table.
    if op.get_bind().dialect.name == "sqlite":
        # SQLite accepts a REFERENCES clause on ADD COLUMN (the default is NULL),
        # but Alembic would only emit it through a table rebuild.
        op.execute("ALTER TABLE users ADD COLUMN invited_by_id INTEGER REFERENCES users (id)")
    else:
        op.add_column("users", sa.Column("invited_by_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_users_invited_by_id", "users", "users", ["invited_by_id"], ["id"])
    op.add_column(
        "users",
        sa.Column("console_root", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_invited_by_id", "users", ["invited_by_id"])

    _classify_existing_members()


def _classify_existing_members() -> None:
    """Make a member without Telegram a console root only when nothing else is possible.

    Before this revision an in-app invitation left no trace, so a member without
    Telegram was created either from the console or by another member — possibly
    a Telegram member since removed from the list, which is the hole this closes.
    That cannot have happened if the database has never had a Telegram member:
    Telegram rows are never deleted by the app, so none means none ever existed.
    A dangling pointer in the history says a member *was* deleted, of unknown
    kind, and then nothing is assumed. Everyone not classified here stays
    unconfirmed and is refused until the operator decides (`app.invite --list`).
    """
    bind = op.get_bind()
    telegram = bind.execute(
        sa.text("SELECT count(*) FROM users WHERE telegram_id IS NOT NULL")
    ).scalar_one()
    dangling = sum(
        bind.execute(
            sa.text(
                f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL "
                f"AND {column} NOT IN (SELECT id FROM users)"
            )
        ).scalar_one()
        for table, column in MEMBER_REFERENCES
    )
    console = bind.execute(
        sa.text("SELECT id, first_name FROM users WHERE telegram_id IS NULL ORDER BY id")
    ).all()
    if not console:
        return

    described = ", ".join(f"{row.id} ({row.first_name})" for row in console)
    if telegram == 0 and dangling == 0:
        # A bound boolean rather than `= 1`, which only SQLite accepts for a BOOLEAN.
        bind.execute(
            sa.text("UPDATE users SET console_root = :root WHERE telegram_id IS NULL"),
            {"root": True},
        )
        log.warning(
            "membership: no Telegram member has ever existed here, so every member "
            "without Telegram was created from the console; confirmed as roots: %s",
            described,
        )
        return

    why = (
        f"{telegram} Telegram member(s) exist"
        if telegram
        else f"{dangling} history reference(s) point at deleted members"
    )
    log.warning(
        "membership: %s, so who let these members in cannot be told; they are refused "
        "until reviewed with `python -m app.invite --list`: %s",
        why,
        described,
    )


def downgrade() -> None:
    # Back to "a row without Telegram is a member"; nothing else depended on these.
    op.drop_index("ix_users_invited_by_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("revoked_at")
        batch.drop_column("console_root")
        batch.drop_column("invited_by_id")

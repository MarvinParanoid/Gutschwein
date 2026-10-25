"""Revision 0010 on databases shaped like the ones already out there.

Each test builds a database at 0009 — the schema every install had before — fills
it the way a real household would have, and upgrades it. What must hold: nothing
is lost, the sessions people are signed in with survive, and a member without
Telegram becomes a console root only when no other origin was possible.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from alembic import command
from app.config import settings
from app.migrations import alembic_config

TABLES = ("users", "vouchers", "events", "comments", "sessions", "login_tokens")


@pytest.fixture
def database(monkeypatch, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A database at revision 0009. Foreign keys are off, as they were back then."""
    path = tmp_path / "old.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(alembic_config(), "0009")
    connection = sqlite3.connect(path)
    yield connection
    connection.close()


@pytest.fixture
def migration_log(capsys):
    """What the operator reads during the upgrade.

    The migration's warnings go through alembic.ini's console handler, which
    `env.py` installs on every run (and which replaces any handler a test could
    attach beforehand), so they are read where they end up: stderr.
    """

    def read() -> list[str]:
        return [line for line in capsys.readouterr().err.splitlines() if "membership:" in line]

    return read


def _member(db: sqlite3.Connection, user_id: int, name: str, telegram_id: int | None = None):
    db.execute(
        "INSERT INTO users (id, telegram_id, first_name, last_name, username, last_seen_at, "
        "created_at) VALUES (?, ?, ?, '', '', '2026-01-01', ?)",
        (user_id, telegram_id, name, f"2026-01-{user_id:02d} 12:00:00"),
    )


def _household_history(db: sqlite3.Connection, author: int, signed_in: list[int]) -> None:
    db.execute(
        "INSERT INTO vouchers (id, status, merchant, title, code, value_kind, value_amount, "
        "balance_amount, currency, conditions, notes, created_by_id) "
        "VALUES (1, 'active', 'Rewe', '', 'C-1', 'amount', 50, 40, 'EUR', '', '', ?)",
        (author,),
    )
    db.execute(
        "INSERT INTO events (voucher_id, actor_id, kind, payload) VALUES "
        '(1, ?, \'balance_updated\', \'{"spent": "10", "remaining": "40", "note": ""}\')',
        (author,),
    )
    db.execute("INSERT INTO comments (voucher_id, author_id, text) VALUES (1, ?, 'hi')", (author,))
    for user_id in signed_in:
        db.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, '2099-01-01')",
            (f"session-{user_id}", user_id),
        )
        db.execute(
            "INSERT INTO login_tokens (token_hash, user_id, expires_at) "
            "VALUES (?, ?, '2099-01-01')",
            (f"token-{user_id}", user_id),
        )
    db.commit()


def _snapshot(db: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Every row of every table, as far as the pre-0010 columns go."""
    snapshot = {}
    for table in TABLES:
        columns = [
            row[1]
            for row in db.execute(f"PRAGMA table_info({table})")
            if row[1] not in ("invited_by_id", "console_root", "revoked_at")
        ]
        snapshot[table] = db.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY 1"
        ).fetchall()
    return snapshot


def _provenance(db: sqlite3.Connection) -> dict[int, tuple]:
    rows = db.execute("SELECT id, console_root, invited_by_id, revoked_at FROM users ORDER BY id")
    return {row[0]: row[1:] for row in rows}


def _upgrade() -> None:
    command.upgrade(alembic_config(), "head")


def test_a_household_without_telegram_keeps_working(database, migration_log) -> None:
    _member(database, 1, "Anna")
    _member(database, 2, "Boris")
    _household_history(database, author=2, signed_in=[1, 2])
    before = _snapshot(database)

    _upgrade()

    assert _snapshot(database) == before
    assert _provenance(database) == {1: (1, None, None), 2: (1, None, None)}
    assert any("confirmed as roots: 1 (Anna), 2 (Boris)" in line for line in migration_log())


def test_a_mixed_family_leaves_the_others_for_the_operator(database, migration_log) -> None:
    # Console member before the first Telegram member, and one after: the order
    # is not taken as proof of anything.
    _member(database, 1, "Early")
    _member(database, 2, "Telegram", telegram_id=555)
    _member(database, 3, "Grandma")
    _household_history(database, author=3, signed_in=[1, 2, 3])
    before = _snapshot(database)

    _upgrade()

    assert _snapshot(database) == before
    assert _provenance(database) == {
        1: (0, None, None),
        2: (0, None, None),
        3: (0, None, None),
    }
    review = [line for line in migration_log() if "refused until reviewed" in line]
    assert review and "1 (Early), 3 (Grandma)" in review[0]
    assert "1 Telegram member(s) exist" in review[0]


def test_a_deleted_member_in_the_history_means_no_assumptions(database, migration_log) -> None:
    """No Telegram row left — but someone was deleted, and nobody knows who."""
    _member(database, 1, "Survivor")
    _household_history(database, author=1, signed_in=[1])
    database.execute("UPDATE events SET actor_id = 99")
    database.commit()

    _upgrade()

    assert _provenance(database) == {1: (0, None, None)}
    assert any("point at deleted members" in line for line in migration_log())


def test_a_telegram_only_household_has_nothing_to_review(database, migration_log) -> None:
    _member(database, 1, "Only", telegram_id=777)
    _household_history(database, author=1, signed_in=[1])
    before = _snapshot(database)

    _upgrade()

    assert _snapshot(database) == before
    assert _provenance(database) == {1: (0, None, None)}
    assert migration_log() == []


def test_an_empty_database_upgrades_quietly(database, migration_log) -> None:
    _upgrade()

    assert _provenance(database) == {}
    assert migration_log() == []


def test_the_new_column_is_a_real_foreign_key(database) -> None:
    _member(database, 1, "Anna")
    database.commit()
    _upgrade()

    # A fresh connection: one opened before the upgrade may answer PRAGMAs from
    # the schema it cached.
    fresh = sqlite3.connect(settings.database_url.split("///", 1)[1])
    try:
        keys = fresh.execute("PRAGMA foreign_key_list(users)").fetchall()
        assert [(k[2], k[3], k[4]) for k in keys] == [("users", "invited_by_id", "id")]
        fresh.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            fresh.execute("UPDATE users SET invited_by_id = 42 WHERE id = 1")
    finally:
        fresh.close()


def test_downgrading_gives_the_old_schema_back_with_the_data(database) -> None:
    _member(database, 1, "Anna")
    _member(database, 2, "Telegram", telegram_id=555)
    _household_history(database, author=1, signed_in=[1, 2])
    before = _snapshot(database)
    _upgrade()

    command.downgrade(alembic_config(), "0009")

    columns = [row[1] for row in database.execute("PRAGMA table_info(users)")]
    assert not {"invited_by_id", "console_root", "revoked_at"} & set(columns)
    assert _snapshot(database) == before

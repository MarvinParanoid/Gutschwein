"""Revision 0011: the database itself allows one voucher per stored picture.

Built from a database at 0010 — the schema right before it — filled the way an
install would be, then upgraded. A picture shared by two cards must stop the
upgrade with a message saying how to fix it, and change nothing.
"""

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from alembic import command
from app.config import settings
from app.migrations import alembic_config

PICTURE = "2026-09/" + "a" * 32 + ".webp"
OTHER = "2026-09/" + "b" * 32 + ".webp"


@pytest.fixture
def database(monkeypatch, tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "old.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(alembic_config(), "0010")
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO users (id, first_name, last_name, username, last_seen_at, console_root) "
        "VALUES (1, 'Anna', '', '', '2026-01-01', 1)"
    )
    connection.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ('h', 1, '2099-01-01')"
    )
    connection.commit()
    yield connection
    connection.close()


def _voucher(db: sqlite3.Connection, voucher_id: int, image_path: str | None) -> None:
    db.execute(
        "INSERT INTO vouchers (id, status, merchant, title, code, value_kind, currency, "
        "conditions, notes, created_by_id, image_path) "
        "VALUES (?, 'active', 'Shop', '', '', 'other', 'EUR', '', '', 1, ?)",
        (voucher_id, image_path),
    )
    db.execute(
        "INSERT INTO events (voucher_id, actor_id, kind, payload) VALUES (?, 1, 'created', '{}')",
        (voucher_id,),
    )
    db.commit()


def _rows(db: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {
        table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in ("users", "vouchers", "events", "sessions")
    }


def _fresh() -> sqlite3.Connection:
    """A connection opened after the migration: an older one may cache the schema."""
    return sqlite3.connect(settings.database_url.split("///", 1)[1])


def _unique_index(db: sqlite3.Connection) -> list[tuple]:
    return [row for row in db.execute("PRAGMA index_list(vouchers)") if row[2]]


def _version(db: sqlite3.Connection) -> str:
    return db.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_unique_pictures_get_the_index_and_keep_everything(database) -> None:
    _voucher(database, 1, PICTURE)
    _voucher(database, 2, OTHER)
    _voucher(database, 3, None)
    _voucher(database, 4, None)  # several cards without a picture are fine
    before = _rows(database)

    command.upgrade(alembic_config(), "0011")

    fresh = _fresh()
    assert _rows(fresh) == before
    assert [row[1] for row in _unique_index(fresh)] == ["ix_vouchers_image_path"]
    with pytest.raises(sqlite3.IntegrityError, match="image_path"):
        fresh.execute("UPDATE vouchers SET image_path = ? WHERE id = 2", (PICTURE,))
    fresh.execute(
        "INSERT INTO vouchers (id, status, merchant, title, code, value_kind, "
        "currency, conditions, notes, created_by_id) VALUES "
        "(5, 'active', 'Shop', '', '', 'other', 'EUR', '', '', 1)"
    )
    fresh.close()


def test_a_shared_picture_stops_the_upgrade_and_says_how_to_fix_it(database) -> None:
    _voucher(database, 1, PICTURE)
    _voucher(database, 2, PICTURE)
    _voucher(database, 3, PICTURE)
    _voucher(database, 4, OTHER)
    before = _rows(database)

    with pytest.raises(RuntimeError) as stopped:
        command.upgrade(alembic_config(), "0011")

    message = str(stopped.value)
    assert f"{PICTURE}: vouchers 1, 2, 3" in message
    assert "changed nothing" in message
    fresh = _fresh()
    assert _rows(fresh) == before
    assert _unique_index(fresh) == []
    assert _version(fresh) == "0010"
    fresh.close()

    # The command in the message is the fix: run its Python, and the upgrade passes.
    snippet = re.search(r'python -c "(.+?)"\n', message).group(1)
    exec(snippet.replace("/data/gutschwein.db", settings.database_url.split("///", 1)[1]))
    command.upgrade(alembic_config(), "0011")

    fresh = _fresh()
    assert fresh.execute("SELECT id, image_path FROM vouchers ORDER BY id").fetchall() == [
        (1, PICTURE),
        (2, None),
        (3, None),
        (4, OTHER),
    ]
    assert _version(fresh) == "0011"
    fresh.close()


def test_an_install_at_0009_with_a_shared_picture_is_left_consistent(
    monkeypatch, tmp_path: Path
) -> None:
    """Production upgrades 0009 → 0011 in one start. Alembic commits each revision on
    SQLite, so 0010 stays applied and only 0011 is held back — a state the next start
    resumes from, rather than half of 0010 that it would trip over."""
    path = tmp_path / "older.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(alembic_config(), "0009")
    db = sqlite3.connect(path)
    db.execute(
        "INSERT INTO users (id, first_name, last_name, username, last_seen_at) "
        "VALUES (1, 'Anna', '', '', '2026-01-01')"
    )
    db.commit()
    _voucher(db, 1, PICTURE)
    _voucher(db, 2, PICTURE)
    db.close()

    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="cannot make pictures unique"):
            command.upgrade(alembic_config(), "head")
        fresh = _fresh()
        assert _version(fresh) == "0010"
        assert "console_root" in [row[1] for row in fresh.execute("PRAGMA table_info(users)")]
        fresh.close()


def test_downgrading_drops_only_the_index(database) -> None:
    _voucher(database, 1, PICTURE)
    _voucher(database, 2, None)
    before = _rows(database)
    command.upgrade(alembic_config(), "0011")

    command.downgrade(alembic_config(), "0010")

    fresh = _fresh()
    assert _unique_index(fresh) == []
    assert _rows(fresh) == before
    assert _version(fresh) == "0010"
    fresh.close()

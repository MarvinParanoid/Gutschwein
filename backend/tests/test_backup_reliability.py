"""Backups that are noticed when they fail, and restore when they are needed (T10).

Every test runs against its own data directory and its own copy of the database
under tmp_path — the session's database is copied once, so the schema is the real
migrated one, and nothing here touches another test's data.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendDocument
from fastapi.testclient import TestClient

from app import backup
from app.config import settings

SECRET_CODE = "SECRET-4711-0815"
PICTURE = "2031-03/0123456789abcdef0123456789abcdef.webp"
METHOD = SendDocument(chat_id=42, document="x")


def _insert(conn: sqlite3.Connection, table: str, **values: object) -> int:
    """A row with the given values and an empty value in every other required column."""
    for _, name, kind, notnull, default, pk in conn.execute(f"PRAGMA table_info({table})"):
        if notnull and default is None and not pk and name not in values:
            values[name] = 0 if kind.upper() in ("INTEGER", "BOOLEAN", "NUMERIC") else ""
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    return conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({marks})", list(values.values())
    ).lastrowid


@pytest.fixture
def data(client: TestClient, tmp_path: Path, monkeypatch) -> Path:
    """An isolated install: a migrated database with one card and its picture."""
    root = tmp_path / "data"
    (root / "uploads" / "2031-03").mkdir(parents=True)
    db = root / "gutschwein.db"
    source = Path(settings.database_url.split("///", 1)[-1])
    with (
        contextlib.closing(sqlite3.connect(source)) as src,
        contextlib.closing(sqlite3.connect(db)) as dst,
    ):
        src.backup(dst)
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute("UPDATE vouchers SET image_path = NULL")
        user = _insert(conn, "users", first_name="Backup", console_root=1)
        _insert(
            conn,
            "vouchers",
            merchant="Backup-Shop",
            code=SECRET_CODE,
            status="active",
            value_kind="other",
            currency="EUR",
            image_path=PICTURE,
            created_by_id=user,
            created_at="2031-03-01 00:00:00",
            updated_at="2031-03-01 00:00:00",
        )
        conn.commit()
    (root / "uploads" / PICTURE).write_bytes(b"picture bytes")

    monkeypatch.setattr(settings, "data_dir", root)
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db}")
    monkeypatch.setattr(settings, "family_chat_id", 42)
    monkeypatch.setattr(settings, "backup_keep", 3)
    monkeypatch.setattr(backup, "SEND_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(backup, "BUILD_RETRY_DELAYS", (0,))
    return root


_kept = 0


def _keep(path: Path) -> Path:
    global _kept
    _kept += 1
    copy = Path(tempfile.gettempdir()) / f"gutschwein-test-sent-{os.getpid()}-{_kept}.tar.gz"
    shutil.copyfile(path, copy)
    return copy


class FakeBot:
    """Records documents and messages; fails the first `failures` uploads."""

    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.attempts = 0
        self.documents: list[Path] = []
        self.messages: list[str] = []

    async def send_document(self, chat_id: int, document, caption: str, **_: object) -> None:
        self.attempts += 1
        if self.failures:
            raise self.failures.pop(0)
        # Keep a copy: the file may be a temporary one that is gone afterwards.
        self.documents.append(await asyncio.to_thread(_keep, Path(document.path)))
        self.messages.append(caption)

    async def send_message(self, chat_id: int, text: str, **_: object) -> None:
        self.messages.append(text)


def _members(archive: Path) -> set[str]:
    with tarfile.open(archive) as tar:
        return set(tar.getnames())


# --- restore -----------------------------------------------------------------------------


def test_a_backup_restores_database_and_pictures(data: Path, tmp_path: Path) -> None:
    archive, checked = backup.store_locally()
    assert checked.missing_images == [] and checked.images == 1

    target = tmp_path / "restored"
    assert backup.main(["extract", str(archive), str(target)]) == 0

    with contextlib.closing(sqlite3.connect(target / "gutschwein.db")) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute(
            "SELECT count(*) FROM vouchers WHERE code = ?", (SECRET_CODE,)
        ).fetchone() == (1,)
    assert (target / "uploads" / PICTURE).read_bytes() == b"picture bytes"


def test_extract_refuses_a_directory_that_is_not_empty(data: Path, tmp_path: Path) -> None:
    archive, _ = backup.store_locally()
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "gutschwein.db").write_bytes(b"precious")

    assert backup.main(["extract", str(archive), str(tmp_path / "live")]) == 1
    assert (tmp_path / "live" / "gutschwein.db").read_bytes() == b"precious"


def test_a_missing_archive_is_reported(data: Path, tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError, match="not found"):
        backup.verify_archive(tmp_path / "nowhere.tar.gz")


@pytest.mark.parametrize("damage", ["truncate", "garble", "empty"])
def test_a_damaged_archive_does_not_pass(data: Path, damage: str) -> None:
    archive, _ = backup.store_locally()
    raw = archive.read_bytes()
    if damage == "truncate":
        archive.write_bytes(raw[: len(raw) // 2])
    elif damage == "garble":
        archive.write_bytes(raw[:100] + bytes(b ^ 0xFF for b in raw[100:300]) + raw[300:])
    else:
        archive.write_bytes(b"")

    with pytest.raises(backup.BackupError):
        backup.verify_archive(archive)


def test_an_archive_without_a_database_does_not_pass(tmp_path: Path, data: Path) -> None:
    archive = tmp_path / "only-pictures.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(data / "uploads" / PICTURE, arcname=f"uploads/{PICTURE}")

    with pytest.raises(backup.BackupError, match="no database"):
        backup.verify_archive(archive)


def test_a_path_escaping_the_target_is_refused(tmp_path: Path, data: Path) -> None:
    archive, _ = backup.store_locally()
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(archive) as src, tarfile.open(evil, "w:gz") as dst:
        for member in src.getmembers():
            dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        payload = data / "uploads" / PICTURE
        dst.add(payload, arcname="../outside.txt")

    with pytest.raises(backup.BackupError, match="unexpected entry"):
        backup.verify_archive(evil)


async def test_a_missing_picture_is_kept_reported_and_counted(data: Path) -> None:
    (data / "uploads" / PICTURE).unlink()
    bot = FakeBot()

    outcome = await backup.run_backup(bot, "test")
    await backup.report_failures(bot, outcome)

    # Still a backup — the database is whole — but nobody is told it is complete.
    assert outcome.local_file is not None and outcome.missing_images == 1
    assert any("нет файла картинки" in m for m in bot.messages)
    assert backup.main(["verify", str(backup.backup_dir() / outcome.local_file)]) == 2


# --- the write-ahead log --------------------------------------------------------------------


def test_rows_still_in_the_write_ahead_log_are_in_the_backup(data: Path, tmp_path: Path) -> None:
    """A copy of the database file alone would miss them; the backup API does not."""
    db = data / "gutschwein.db"
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE vouchers SET notes = 'only in the wal' WHERE merchant = 'Backup-Shop'")
    writer.commit()
    try:
        assert (data / "gutschwein.db-wal").stat().st_size > 0  # not checkpointed
        archive, _ = backup.store_locally()
    finally:
        writer.close()

    assert not any(name.endswith(("-wal", "-shm")) for name in _members(archive))
    backup.main(["extract", str(archive), str(tmp_path / "r")])
    with contextlib.closing(sqlite3.connect(tmp_path / "r" / "gutschwein.db")) as restored:
        assert restored.execute(
            "SELECT notes FROM vouchers WHERE merchant = 'Backup-Shop'"
        ).fetchone() == ("only in the wal",)


def test_the_snapshot_leaves_no_database_open(data: Path) -> None:
    """`with sqlite3.connect()` only commits; both connections used to stay open."""

    def open_files() -> set[str]:
        names = set()
        for fd in Path("/proc/self/fd").iterdir():
            with contextlib.suppress(OSError):
                target = os.readlink(fd)
                if "gutschwein" in Path(target).name:
                    names.add(target)
        return names

    if not Path("/proc/self/fd").exists():
        pytest.skip("needs /proc")
    before = open_files()
    backup.store_locally()
    assert open_files() <= before


# --- interrupted runs and the last good backup -------------------------------------------------


def test_an_interrupted_run_leaves_no_backup_lookalike_and_keeps_the_good_ones(
    data: Path, monkeypatch
) -> None:
    good, _ = backup.store_locally(datetime(2031, 3, 1, tzinfo=UTC))

    def crash(*_: object, **__: object):
        raise backup.BackupError("database in archive fails integrity_check")

    monkeypatch.setattr(backup, "verify_archive", crash)
    with pytest.raises(backup.BackupError):
        backup.store_locally(datetime(2031, 3, 2, tzinfo=UTC))

    assert backup.local_archives() == [good]
    assert list(backup.backup_dir().glob("*.partial")) == []


def test_a_partial_file_from_a_crashed_run_is_never_a_backup_and_is_swept(data: Path) -> None:
    backup.backup_dir().mkdir(parents=True)
    crashed = backup.backup_dir() / "gutschwein-2031-03-01T040000Z.tar.gz.partial"
    crashed.write_bytes(b"half")
    old = time.time() - 7200
    os.utime(crashed, (old, old))

    assert backup.local_archives() == []
    backup.store_locally()

    assert not crashed.exists()
    assert len(backup.local_archives()) == 1


def test_rotation_keeps_the_newest_and_never_the_last_one(data: Path, monkeypatch) -> None:
    made = [backup.store_locally(datetime(2031, 3, day, 4, tzinfo=UTC))[0] for day in range(1, 6)]
    assert backup.local_archives() == made[-3:]

    monkeypatch.setattr(settings, "backup_keep", 0)
    backup.rotate()
    assert backup.local_archives() == made[-1:]


async def test_a_failed_run_deletes_nothing(data: Path, monkeypatch) -> None:
    good, _ = backup.store_locally(datetime(2031, 3, 1, tzinfo=UTC))
    monkeypatch.setattr(
        backup,
        "_build_archive",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError(28, "No space left")),
    )
    bot = FakeBot()

    outcome = await backup.run_backup(bot, "test")
    await backup.report_failures(bot, outcome)

    assert outcome.local_error == "OSError ENOSPC"
    assert backup.local_archives() == [good]
    assert any("Бэкап на сервере не получился" in m and "ENOSPC" in m for m in bot.messages)


# --- one at a time ------------------------------------------------------------------------


async def test_concurrent_runs_do_not_overlap(data: Path) -> None:
    results = await asyncio.gather(
        backup.run_backup(None, "one"), backup.run_backup(None, "two"), return_exceptions=True
    )

    assert sum(isinstance(r, backup.BackupBusy) for r in results) == 1
    assert len(backup.local_archives()) == 1


async def test_a_run_in_another_process_is_respected(data: Path) -> None:
    """The file lock, as a console `python -m app.backup now` would hold it."""
    held, release = threading.Event(), threading.Event()

    def other_process() -> None:
        with backup._exclusive():
            held.set()
            release.wait(5)

    thread = threading.Thread(target=other_process)
    thread.start()
    held.wait(5)
    try:
        with pytest.raises(backup.BackupBusy):
            await backup.run_backup(None, "test")
    finally:
        release.set()
        thread.join()
    assert backup.local_archives() == []


# --- Telegram -------------------------------------------------------------------------------


async def test_a_transient_upload_failure_is_retried(data: Path) -> None:
    bot = FakeBot([TelegramNetworkError(METHOD, "down"), TelegramRetryAfter(METHOD, "slow", 0)])

    outcome = await backup.run_backup(bot, "test")

    assert bot.attempts == 3
    assert outcome.telegram == "sent" and outcome.ok
    assert backup.read_status()["last_telegram_success"] == outcome.started
    # What reached the chat is the verified archive, pictures included.
    assert backup.verify_archive(bot.documents[0]).images == 1


async def test_a_telegram_outage_leaves_a_local_backup_and_says_so(data: Path) -> None:
    bot = FakeBot([TelegramNetworkError(METHOD, "down")] * 5)

    outcome = await backup.run_backup(bot, "test")
    await backup.report_failures(bot, outcome)

    assert bot.attempts == 3  # bounded: the first try and two retries
    assert outcome.telegram == "failed" and not outcome.ok
    assert outcome.local_file is not None
    assert backup.verify_archive(backup.backup_dir() / outcome.local_file).images == 1
    status = backup.read_status()
    assert "last_local_success" in status and "last_telegram_success" not in status
    assert any("не дошёл до чата" in m and "✓" in m for m in bot.messages)


async def test_a_permanent_upload_error_is_not_retried(data: Path) -> None:
    bot = FakeBot([TelegramBadRequest(METHOD, "chat not found")])

    outcome = await backup.run_backup(bot, "test")

    assert bot.attempts == 1
    assert outcome.telegram == "failed"


async def test_the_next_run_after_a_failed_upload_sends_normally(data: Path) -> None:
    await backup.run_backup(FakeBot([TelegramNetworkError(METHOD, "down")] * 5), "day 1")

    bot = FakeBot()
    outcome = await backup.run_backup(bot, "day 2")

    assert outcome.telegram == "sent" and len(bot.documents) == 1


async def test_nothing_of_the_contents_reaches_the_log(data: Path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    bot = FakeBot([TelegramNetworkError(METHOD, "down")] * 5)

    outcome = await backup.run_backup(bot, "test")
    await backup.report_failures(bot, outcome)

    assert SECRET_CODE not in caplog.text
    assert PICTURE not in caplog.text
    assert "0123456789abcdef" not in " ".join(bot.messages)


# --- the schedule ---------------------------------------------------------------------------


def _at(hour: int, day: int = 14) -> datetime:
    return datetime(2031, 3, day, hour, 5, tzinfo=UTC)


async def test_the_schedule_runs_once_a_day_and_catches_up(data: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "backup_hour_utc", 4)
    bot = FakeBot()

    assert await backup.scheduled_tick(bot, _at(3)) is None  # not yet
    # Down at four, back at three in the afternoon: it runs then.
    assert await backup.scheduled_tick(bot, _at(15)) is not None
    assert await backup.scheduled_tick(bot, _at(16)) is None  # once
    assert await backup.scheduled_tick(bot, _at(5, day=15)) is not None  # the next day

    assert len(bot.documents) == 2


async def test_the_marker_of_the_previous_version_counts_for_today(data: Path) -> None:
    (data / ".last_backup").write_text(_at(4).strftime("%Y-%m-%d"))

    assert await backup.scheduled_tick(FakeBot(), _at(9)) is None


async def test_a_backup_that_stopped_happening_is_reported_once_a_day(
    data: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "backup_hour_utc", 4)
    await backup.scheduled_tick(FakeBot(), _at(5, day=1))  # the schedule ran once
    bot = FakeBot()
    # Days later, today's run already recorded (say, by a run whose archive was
    # then lost): nothing new is due, and the newest backup is far too old.
    status = backup.read_status()
    status["last_scheduled_day"] = _at(5, day=14).strftime("%Y-%m-%d")
    backup._save_status(status)

    await backup.scheduled_tick(bot, _at(6, day=14))
    await backup.scheduled_tick(bot, _at(7, day=14))

    assert sum("Свежего бэкапа нет" in m for m in bot.messages) == 1


async def test_a_fresh_install_is_not_told_it_is_late(data: Path) -> None:
    bot = FakeBot()

    await backup.scheduled_tick(bot, _at(2))

    assert bot.messages == []


# --- independent of the bot ----------------------------------------------------------------


def test_backups_run_without_a_bot_and_outlive_a_stopped_one(
    client: TestClient, monkeypatch
) -> None:
    """The loops used to be tasks of the bot's polling and ended with it."""
    import app.bot
    import app.main

    events: list[str] = []

    async def fake_backup_loop(bot) -> None:
        events.append(f"backup started, bot={'yes' if bot else 'no'}")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("backup cancelled")
            raise

    async def fake_reminders() -> None:
        events.append("reminders started")
        await asyncio.sleep(3600)

    async def polling_dies(_bot) -> None:
        raise RuntimeError("Unauthorized: the token was revoked")

    monkeypatch.setattr(app.main, "backup_loop", fake_backup_loop)

    # No bot at all: the local backup still runs.
    monkeypatch.setattr(settings, "run_bot", False)
    with TestClient(app.main.app):
        time.sleep(0.05)
        assert events == ["backup started, bot=no"]

    # A bot whose polling dies at once: the loops keep running until shutdown.
    events.clear()
    monkeypatch.setattr(settings, "run_bot", True)
    monkeypatch.setattr(settings, "bot_token", "1:test")
    monkeypatch.setattr(app.bot, "run_bot", polling_dies)
    monkeypatch.setattr(app.bot, "background_loops", lambda _bot: [fake_reminders()])
    with TestClient(app.main.app):
        time.sleep(0.05)
        assert "reminders started" in events
        assert "backup started, bot=yes" in events
        assert "backup cancelled" not in events
    assert "backup cancelled" in events  # only by the shutdown

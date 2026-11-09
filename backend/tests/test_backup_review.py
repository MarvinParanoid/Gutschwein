"""Release review of the backup job: the cases test_backup_reliability.py left open.

Same isolated data directory (the `data` fixture), so nothing here touches another
test's files.
"""

import asyncio
import errno
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram.exceptions import TelegramNetworkError

from app import backup
from tests.test_backup_reliability import METHOD, PICTURE, FakeBot, data  # noqa: F401


def _full_disk(*_: object, **__: object) -> None:
    raise OSError(errno.ENOSPC, "No space left on device")


# --- 1, 2: an archive never contains backups ------------------------------------------------


def test_archives_never_contain_earlier_archives_and_do_not_grow(data: Path) -> None:  # noqa: F811
    sizes = []
    for day in range(1, 5):
        archive, _ = backup.store_locally(datetime(2031, 3, day, 4, tzinfo=UTC))
        with tarfile.open(archive) as tar:
            names = tar.getnames()
        assert names == ["gutschwein.db", f"uploads/{PICTURE}"]
        assert not any("backups" in n or n.endswith(".tar.gz") for n in names)
        sizes.append(archive.stat().st_size)

    # Same data, same size, give or take gzip's timestamps — not one archive more each time.
    assert max(sizes) - min(sizes) < 512


# --- 3: a failed upload does not rebuild ----------------------------------------------------


async def test_a_failing_upload_is_retried_with_the_same_archive(data: Path, monkeypatch) -> None:  # noqa: F811
    built = []
    real = backup._build_archive
    monkeypatch.setattr(backup, "_build_archive", lambda *a, **k: built.append(1) or real(*a, **k))
    bot = FakeBot([TelegramNetworkError(METHOD, "down")] * 5)

    await backup.run_backup(bot, "test")

    assert bot.attempts == 3
    assert len(built) == 1  # one archive, sent three times


async def test_a_failed_upload_is_not_retried_by_the_schedule_the_same_day(data: Path) -> None:  # noqa: F811
    bot = FakeBot([TelegramNetworkError(METHOD, "down")] * 10)

    await backup.scheduled_tick(bot, datetime(2031, 3, 14, 5, tzinfo=UTC))
    await backup.scheduled_tick(bot, datetime(2031, 3, 14, 6, tzinfo=UTC))

    assert bot.attempts == 3
    assert len(backup.local_archives()) == 1


# --- 5, 9: a full disk ----------------------------------------------------------------------


async def test_a_full_disk_is_reported_even_when_the_status_cannot_be_written(
    data: Path,  # noqa: F811
    monkeypatch,
) -> None:
    """The status file is on the same full disk. Its write used to raise out of the
    run before the chat was told, and the day was never recorded — so the job tried
    again every 15 minutes, saying nothing but a log line each time."""
    monkeypatch.setattr(backup, "_build_archive", _full_disk)
    monkeypatch.setattr(backup, "_save_status", _full_disk)
    bot = FakeBot()

    first = await backup.scheduled_tick(bot, datetime(2031, 3, 14, 5, tzinfo=UTC))
    again = await backup.scheduled_tick(bot, datetime(2031, 3, 14, 5, 15, tzinfo=UTC))

    assert first is not None and first.local_error == "OSError ENOSPC"
    assert any("ENOSPC" in m for m in bot.messages)
    assert again is None  # the day counts as attempted, even with nowhere to write it
    assert sum("ENOSPC" in m for m in bot.messages) == 1


async def test_the_loop_survives_whatever_a_tick_raises(data: Path, monkeypatch) -> None:  # noqa: F811
    ticks = []

    async def broken_tick(_bot):
        ticks.append(1)
        raise RuntimeError("anything at all")

    real_sleep = asyncio.sleep

    async def short_sleep(_seconds: float) -> None:
        if len(ticks) >= 3:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(backup, "scheduled_tick", broken_tick)
    monkeypatch.setattr(backup, "STARTUP_DELAY", 0)
    monkeypatch.setattr(backup.asyncio, "sleep", short_sleep)

    with pytest.raises(asyncio.CancelledError):
        await backup.backup_loop(None)

    assert len(ticks) == 3  # kept going until it was cancelled, not stopped by an error


def test_a_disk_error_while_checking_is_not_called_a_bad_archive(data: Path, monkeypatch) -> None:  # noqa: F811
    archive, _ = backup.store_locally()
    monkeypatch.setattr(backup.tempfile, "TemporaryDirectory", _full_disk)

    with pytest.raises(backup.BackupError) as raised:
        backup.verify_archive(archive)

    assert "ENOSPC" in str(raised.value)


# --- 6: the newest good archive survives rotation --------------------------------------------


def test_the_archive_just_written_survives_a_clock_that_went_back(data: Path) -> None:  # noqa: F811
    later = [
        backup.store_locally(datetime(2031, 3, day, 4, tzinfo=UTC))[0] for day in range(10, 13)
    ]
    # The clock jumped back a week: the new archive's name sorts as the oldest.
    written, _ = backup.store_locally(datetime(2031, 3, 3, 4, tzinfo=UTC))

    assert written.exists()
    assert written in backup.local_archives()
    assert len(backup.local_archives()) == 3
    assert later[-1].exists()


# --- 10: nothing from inside an archive in a message -------------------------------------------


def test_an_unexpected_entry_is_not_named(data: Path, tmp_path: Path) -> None:  # noqa: F811
    evil = tmp_path / "evil.tar.gz"
    secret_name = "../2031-03/ffffffffffffffffffffffffffffffff.webp"
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(data / "uploads" / PICTURE, arcname=secret_name)

    with pytest.raises(backup.BackupError) as raised:
        backup.verify_archive(evil)

    assert "ffffffff" not in str(raised.value)


async def test_no_room_even_for_the_lock_file_is_reported_once(data: Path, monkeypatch) -> None:  # noqa: F811
    def no_lock():
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(backup, "_exclusive", no_lock)
    bot = FakeBot()

    await backup.scheduled_tick(bot, datetime(2031, 3, 14, 5, tzinfo=UTC))
    await backup.scheduled_tick(bot, datetime(2031, 3, 14, 5, 15, tzinfo=UTC))

    assert sum("ENOSPC" in m for m in bot.messages) == 1

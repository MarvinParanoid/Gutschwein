"""Nightly backup: kept on the server, and sent to the family chat.

The whole state is one SQLite file plus the uploads directory. Every night the
app packs both into one archive, checks that the archive restores, keeps it in
`DATA_DIR/backups` and sends it to the family chat — a place the family already
reads, so it doubles as free off-site storage.

Two destinations because each covers the other's failure (T10):
- the **local copy** does not depend on Telegram at all. An outage, a revoked bot
  token or a chat the bot was removed from cannot leave the family without a
  usable backup; it is also the only automatic backup of an install without a
  bot. It lives on the same disk as the data, so it does not survive losing the
  machine.
- the **chat copy** is off the machine, and it is what survives a lost server.

A backup counts only once the archive has been read back: the database inside
passes `PRAGMA integrity_check`, and every picture the cards point at is in it.
The local copy is written under a temporary name and renamed into place, so an
interrupted run leaves no file that looks like a backup. Rotation runs only after
a new verified archive is in place and keeps the newest `BACKUP_KEEP`, so the last
good one is never deleted.

A failure is not only logged. The job retries what is worth retrying, and what
still fails is posted to the family chat — so a broken backup is noticed by the
people who would lose the data, not by whoever next reads the server log. The
outcome of the last run is kept in `DATA_DIR/.backup_status.json`, read by
`python -m app.backup status`.

The database is snapshotted through sqlite3's online backup API rather than copied:
a plain file copy taken while the app is writing can be a torn, unusable database,
and the API also folds in what is still in the write-ahead log.

Nothing here logs what an archive contains — sizes and counts only.
"""

import asyncio
import contextlib
import errno
import fcntl
import json
import logging
import os
import sqlite3
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from aiogram import Bot
from aiogram.exceptions import (
    TelegramEntityTooLarge,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import FSInputFile

from app.config import settings
from app.i18n import group_t

log = logging.getLogger(__name__)

# Bots may upload up to 50 MB; stay clear of the edge.
MAX_UPLOAD_BYTES = 45 * 1024 * 1024
# The day's run is due from BACKUP_HOUR_UTC on; checked this often, so a server
# that was down at that hour catches up within one interval of coming back.
CHECK_INTERVAL = 15 * 60
# Telegram: transient failures are tried again after these pauses, then given up
# for the day. A RetryAfter from Telegram is honoured, up to the cap.
SEND_RETRY_DELAYS = (60, 300)
MAX_RETRY_AFTER = 600
# Building the archive: a second try covers a busy moment, not a full disk.
BUILD_RETRY_DELAYS = (30,)
# The first check waits this long after start-up: a restart or a deploy is not the
# moment for a backup, and a test run never lives this long.
STARTUP_DELAY = 120
# No good local backup for this long is reported even if every run "succeeded".
STALE_AFTER = timedelta(hours=36)

STATUS_FILE = ".backup_status.json"
LOCK_FILE = ".backup.lock"
LOCAL_PREFIX = "gutschwein-"
LOCAL_SUFFIX = ".tar.gz"
PARTIAL_SUFFIX = ".partial"

TRANSIENT = (TelegramNetworkError, TelegramServerError, TelegramRetryAfter, OSError, TimeoutError)


class BackupError(Exception):
    """The backup could not be made or did not pass its check."""


class BackupBusy(BackupError):
    """Another backup is running right now."""


@dataclass
class Checked:
    """What reading an archive back found."""

    size: int
    vouchers: int
    images: int
    # Pictures the cards point at that are not in the archive. Listed by count
    # only in any message: the names are capability URLs.
    missing_images: list[str] = field(default_factory=list)
    revision: str = ""


@dataclass
class Outcome:
    """One run of the job, as the status file and the caller see it."""

    started: str
    local_file: str | None = None
    local_error: str | None = None
    telegram: str = "skipped"  # "sent", "failed", "skipped"
    telegram_error: str | None = None
    summary: str = ""
    images: int = 0
    missing_images: int = 0

    @property
    def ok(self) -> bool:
        return self.local_error is None and self.telegram != "failed"


# --- where things are ----------------------------------------------------------------


def database_file() -> Path | None:
    """The SQLite file behind DATABASE_URL, if that is what we are running on."""
    url = settings.database_url
    if "sqlite" not in url:
        return None
    path = url.split("///", 1)[-1]
    return Path(path) if path else None


def backup_dir() -> Path:
    return settings.data_dir / "backups"


def local_archives() -> list[Path]:
    """Finished local backups, oldest first. Every one passed its check."""
    directory = backup_dir()
    if not directory.exists():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.name.startswith(LOCAL_PREFIX) and p.name.endswith(LOCAL_SUFFIX)
    )


# --- building and checking -------------------------------------------------------------


def _snapshot_database(source: Path, target: Path) -> None:
    """Consistent copy of a live database (sqlite's own backup API).

    `with sqlite3.connect()` only commits; it never closes. Both connections are
    closed explicitly, or every backup left two file descriptors open.
    """
    with (
        contextlib.closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as src,
        contextlib.closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)


def _build_archive(target: Path, include_uploads: bool) -> int:
    """Pack the snapshot (and optionally the pictures) into `target`. Returns images."""
    db = database_file()
    if db is None or not db.exists():
        raise BackupError("no database file to back up")
    images = 0
    with tempfile.TemporaryDirectory(prefix="gutschwein-snapshot-") as tmp:
        snapshot = Path(tmp) / "gutschwein.db"
        _snapshot_database(db, snapshot)
        with tarfile.open(target, "w:gz") as tar:
            tar.add(snapshot, arcname="gutschwein.db")
            if include_uploads and settings.upload_dir.exists():
                for image in sorted(settings.upload_dir.rglob("*")):
                    if image.is_file():
                        relative = image.relative_to(settings.upload_dir)
                        tar.add(image, arcname=str(Path("uploads") / relative))
                        images += 1
    return images


def _safe_members(tar: tarfile.TarFile) -> Iterator[tarfile.TarInfo]:
    for member in tar.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
            # Not named: an entry's name may be a picture's capability URL.
            raise BackupError("unexpected entry in archive")
        yield member


def verify_archive(archive: Path, expect_images: bool = True) -> Checked:
    """Read an archive back and check that it would restore. Raises BackupError.

    Reads the whole stream, so a truncated or corrupted file fails here (gzip
    checks its CRC at the end), not on the day it is needed.
    """
    if not archive.is_file():
        raise BackupError("archive not found")
    try:
        with tempfile.TemporaryDirectory(prefix="gutschwein-verify-") as tmp:
            with tarfile.open(archive, "r:gz") as tar:
                members = list(_safe_members(tar))
                names = {m.name for m in members if m.isfile()}
                if "gutschwein.db" not in names:
                    raise BackupError("archive has no database")
                tar.extract("gutschwein.db", path=tmp, filter="data")
                # Touch every member's data: that is what finds a truncated file.
                for member in members:
                    if member.isfile():
                        stream = tar.extractfile(member)
                        while stream is not None and stream.read(1 << 20):
                            pass
            with contextlib.closing(sqlite3.connect(Path(tmp) / "gutschwein.db")) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("database in archive fails integrity_check")
                tables = {
                    r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if not {"vouchers", "users", "events", "alembic_version"} <= tables:
                    raise BackupError("database in archive is missing tables")
                vouchers = db.execute("SELECT count(*) FROM vouchers").fetchone()[0]
                revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                pictures = [
                    r[0]
                    for r in db.execute(
                        "SELECT image_path FROM vouchers WHERE image_path IS NOT NULL"
                    )
                ]
    except OSError as exc:
        if isinstance(exc, FileNotFoundError) or exc.errno not in (errno.ENOSPC, errno.EDQUOT):
            raise BackupError(f"archive cannot be read: {type(exc).__name__}") from exc
        # A full disk where the archive is unpacked says nothing about the archive.
        raise BackupError(f"cannot check the archive: {_describe(exc)}") from exc
    except (tarfile.TarError, EOFError, sqlite3.DatabaseError) as exc:
        raise BackupError(f"archive cannot be read: {type(exc).__name__}") from exc

    images = sum(1 for n in names if n.startswith("uploads/"))
    missing = [p for p in pictures if f"uploads/{p}" not in names] if expect_images else []
    return Checked(
        size=archive.stat().st_size,
        vouchers=vouchers,
        images=images,
        missing_images=missing,
        revision=revision,
    )


def _summary(checked: Checked, note: str = "") -> str:
    if checked.missing_images:
        note += group_t("backup.images_missing", count=len(checked.missing_images))
    return group_t(
        "backup.summary", size=f"{checked.size / 1024 / 1024:.1f}", images=checked.images, note=note
    )


def create_archive(workdir: Path) -> tuple[Path, str]:
    """Archive for the chat, plus a summary; drops the pictures if it is too big.

    Kept for the chat copy: Telegram takes 50 MB. The local copy always has them.
    """
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    archive = workdir / f"gutschwein-{stamp}.tar.gz"
    _build_archive(archive, include_uploads=True)
    note = ""
    if archive.stat().st_size > MAX_UPLOAD_BYTES:
        # Losing the images from one archive beats losing the backup entirely.
        archive.unlink(missing_ok=True)
        _build_archive(archive, include_uploads=False)
        note = group_t("backup.images_dropped", limit=MAX_UPLOAD_BYTES // 1024 // 1024)
        return archive, _summary(verify_archive(archive, expect_images=False), note)
    return archive, _summary(verify_archive(archive))


# --- the local copy ----------------------------------------------------------------------


def store_locally(now: datetime | None = None) -> tuple[Path, Checked]:
    """Build, check and keep one archive in `backup_dir()`. Then rotate.

    The file is written as `*.partial` and renamed only after it passed its check,
    so whatever is named like a backup is one. Rotation comes after, and keeps the
    newest `BACKUP_KEEP` — the one just written is always among them.
    """
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H%M%SZ")
    final = directory / f"{LOCAL_PREFIX}{stamp}{LOCAL_SUFFIX}"
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    try:
        _build_archive(partial, include_uploads=True)
        os.chmod(partial, 0o600)
        checked = verify_archive(partial)
        with open(partial, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(partial, final)
    finally:
        partial.unlink(missing_ok=True)
    rotate(protect=final)
    return final, checked


def rotate(keep: int | None = None, protect: Path | None = None) -> list[Path]:
    """Delete local archives beyond the newest `keep`, and leftover partial files.

    Never leaves fewer than one: with keep < 1 it still keeps the newest. `protect`
    is the archive just written, which stays whatever its name: archives are ordered
    by the time in their names, and after the clock went back the newest backup
    would sort as the oldest and be the first one deleted.
    """
    keep = max(1, settings.backup_keep if keep is None else keep)
    archives = [p for p in local_archives() if p != protect]
    if protect is not None and protect.exists():
        keep -= 1
    removed = []
    for old in archives[: max(0, len(archives) - keep)]:
        old.unlink(missing_ok=True)
        removed.append(old)
    directory = backup_dir()
    if directory.exists():
        for partial in directory.glob(f"*{PARTIAL_SUFFIX}"):
            # A run in progress holds the lock; anything older is a crashed run.
            if datetime.now(UTC).timestamp() - partial.stat().st_mtime > 3600:
                partial.unlink(missing_ok=True)
    return removed


# --- status --------------------------------------------------------------------------------


def _status_path() -> Path:
    return settings.data_dir / STATUS_FILE


def read_status() -> dict:
    try:
        return json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_status(status: dict) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    tmp = _status_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2))
    os.replace(tmp, _status_path())


def _try_save_status(status: dict) -> None:
    """The status is bookkeeping. On a full disk it cannot be written — and that
    must not stop the run from reporting the full disk, which is the news."""
    try:
        _save_status(status)
    except OSError as exc:
        log.error("backup status could not be written: %s", _describe(exc))


def _write_status(outcome: Outcome, scheduled_day: str | None) -> None:
    status = read_status()
    status["last_run"] = asdict(outcome)
    if scheduled_day is not None:
        status["last_scheduled_day"] = scheduled_day
    if outcome.local_file:
        status["last_local_success"] = outcome.started
    if outcome.telegram == "sent":
        status["last_telegram_success"] = outcome.started
    _try_save_status(status)


def newest_good_backup_age(now: datetime | None = None) -> timedelta | None:
    """How old the newest local archive is, judged by its name; None if there is none."""
    archives = local_archives()
    if not archives:
        return None
    stamp = archives[-1].name.removeprefix(LOCAL_PREFIX).removesuffix(LOCAL_SUFFIX)
    made = datetime.strptime(stamp, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - made


# --- one run --------------------------------------------------------------------------------

_running = asyncio.Lock()


@contextlib.contextmanager
def _exclusive() -> Iterator[None]:
    """One backup at a time, also across processes (a console run, a second app)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with open(settings.data_dir / LOCK_FILE, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupBusy("another backup is running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _describe(exc: BaseException) -> str:
    """For the chat and the status file: the kind of failure, never a path or content."""
    if isinstance(exc, BackupError):
        return str(exc)
    if isinstance(exc, OSError) and exc.errno in errno.errorcode:
        return f"{type(exc).__name__} {errno.errorcode[exc.errno]}"  # e.g. ENOSPC, a full disk
    return type(exc).__name__


def _chat_archive(workdir: Path, local: Path | None, summary: str) -> tuple[Path, str]:
    """What goes to the chat: the local archive itself when it fits Telegram's limit
    (one snapshot, checked once), otherwise a fresh one that does — see create_archive."""
    if local is not None and local.stat().st_size <= MAX_UPLOAD_BYTES:
        return local, summary
    return create_archive(workdir)


async def _send_with_retries(bot: Bot, archive: Path, caption: str) -> None:
    """Send the chat copy, retrying transient failures a bounded number of times."""
    delays = list(SEND_RETRY_DELAYS)
    name = f"gutschwein-{datetime.now(UTC).strftime('%Y-%m-%d')}.tar.gz"
    while True:
        try:
            await bot.send_document(
                settings.family_chat_id,
                FSInputFile(archive, filename=name),
                caption=caption,
                disable_notification=True,
            )
            return
        except asyncio.CancelledError:
            raise
        except TelegramEntityTooLarge:
            raise  # a network-error subclass, but trying again changes nothing
        except TRANSIENT as exc:
            if not delays:
                raise
            delay = delays.pop(0)
            if isinstance(exc, TelegramRetryAfter):
                delay = min(max(delay, exc.retry_after), MAX_RETRY_AFTER)
            log.warning("backup upload failed (%s); retrying in %ss", type(exc).__name__, delay)
            await asyncio.sleep(delay)


async def run_backup(bot: Bot | None, reason: str, scheduled_day: str | None = None) -> Outcome:
    """Keep a verified archive locally, then send one to the family chat.

    The local copy comes first and does not depend on the chat. A chat failure
    after it leaves a usable backup on the server, and is reported, not hidden.
    Raises BackupBusy if another run holds the lock.
    """
    if _running.locked():
        raise BackupBusy("another backup is running")
    async with _running:
        with _exclusive():
            outcome = Outcome(started=datetime.now(UTC).isoformat(timespec="seconds"))

            delays = list(BUILD_RETRY_DELAYS)
            while True:
                try:
                    path, checked = await asyncio.to_thread(store_locally)
                    outcome.local_file = path.name
                    outcome.local_error = None
                    outcome.images = checked.images
                    outcome.missing_images = len(checked.missing_images)
                    outcome.summary = _summary(checked)
                    break
                except Exception as exc:  # noqa: BLE001 - recorded and reported
                    outcome.local_error = _describe(exc)
                    if not delays:
                        log.error("local backup failed: %s", outcome.local_error)
                        break
                    await asyncio.sleep(delays.pop(0))

            if bot is not None and settings.family_chat_id is not None:
                local = backup_dir() / outcome.local_file if outcome.local_file else None
                try:
                    with tempfile.TemporaryDirectory(prefix="gutschwein-backup-") as tmp:
                        archive, summary = await asyncio.to_thread(
                            _chat_archive, Path(tmp), local, outcome.summary
                        )
                        outcome.summary = outcome.summary or summary
                        caption = group_t(
                            "backup.caption",
                            stamp=datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC"),
                            summary=summary,
                            reason=reason,
                        )
                        await _send_with_retries(bot, archive, caption)
                    outcome.telegram = "sent"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - recorded and reported
                    outcome.telegram = "failed"
                    outcome.telegram_error = _describe(exc)
                    log.error("backup upload to the chat failed: %s", outcome.telegram_error)

            _write_status(outcome, scheduled_day)
            log.info(
                "backup: local=%s telegram=%s images=%s missing=%s",
                "ok" if outcome.local_file else "FAILED",
                outcome.telegram,
                outcome.images,
                outcome.missing_images,
            )
            return outcome


async def send_backup(bot: Bot, reason: str) -> str:
    """The bot's /backup command: run now, return the summary, raise on failure."""
    if settings.family_chat_id is None:
        raise RuntimeError(group_t("error.no_chat_for_backup"))
    outcome = await run_backup(bot, reason)
    if outcome.local_error:
        raise BackupError(outcome.local_error)
    if outcome.telegram == "failed":
        raise BackupError(outcome.telegram_error or "upload failed")
    return outcome.summary


async def _report(bot: Bot | None, text: str) -> None:
    """Tell the family chat; if even that fails, the log is all that is left."""
    if bot is None or settings.family_chat_id is None:
        log.error("backup problem, and no chat to report it to: %s", text)
        return
    try:
        await bot.send_message(settings.family_chat_id, text, disable_notification=False)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - nothing more to try
        log.error("backup problem could not be reported to the chat: %s", text)


async def report_failures(bot: Bot | None, outcome: Outcome) -> None:
    if outcome.local_error:
        await _report(bot, group_t("backup.failed_local", error=outcome.local_error))
    # Without a local archive the chat copy is rebuilt, and on a full disk it fails
    # the same way: one message for one cause.
    same_cause = outcome.local_error and outcome.telegram_error == outcome.local_error
    if outcome.telegram == "failed" and not same_cause:
        await _report(
            bot,
            group_t(
                "backup.failed_chat",
                error=outcome.telegram_error or "",
                kept="✓" if outcome.local_file else "✗",
            ),
        )
    if outcome.missing_images:
        await _report(bot, group_t("backup.missing_report", count=outcome.missing_images))


# --- the schedule -------------------------------------------------------------------------


LEGACY_MARKER = ".last_backup"
_attempted: dict[str, str | None] = {"day": None}


def _due(now: datetime) -> str | None:
    """Today's date if today's scheduled run is due and has not run; else None.

    Due from BACKUP_HOUR_UTC on, not only within that hour: a server that was down
    then catches up when it is back. The marker of the version before this one
    still counts, so the day this ships does not get a second chat backup.
    """
    if now.hour < settings.backup_hour_utc:
        return None
    today = now.strftime("%Y-%m-%d")
    # The status file, and this process's memory of it for when the file could not
    # be written (a full disk): either way, one scheduled run a day.
    if today in (read_status().get("last_scheduled_day"), _attempted["day"]):
        return None
    with contextlib.suppress(OSError):
        if (settings.data_dir / LEGACY_MARKER).read_text().strip() == today:
            return None
    return today


async def scheduled_tick(bot: Bot | None, now: datetime | None = None) -> Outcome | None:
    """One check of the schedule: run if due, report what failed, warn if stale."""
    now = now or datetime.now(UTC)
    day = _due(now)
    outcome = None
    if day is not None:
        try:
            outcome = await run_backup(bot, group_t("backup.reason_scheduled"), scheduled_day=day)
        except BackupBusy:
            return None  # a manual run is in progress; this one comes back next tick
        except Exception as exc:  # noqa: BLE001 - e.g. no room even for the lock file
            outcome = Outcome(started=now.isoformat(timespec="seconds"), local_error=_describe(exc))
            log.error("backup could not start: %s", outcome.local_error)
        _attempted["day"] = day
        await report_failures(bot, outcome)

    # A run that failed has just said so. Otherwise: is there a recent good backup at
    # all? That catches what no single run reports — the schedule not running, or
    # the archives gone. Not before the first scheduled run: a fresh install has
    # nothing to be late with.
    status = read_status()
    age = newest_good_backup_age(now)
    stale = "last_scheduled_day" in status and (age is None or age > STALE_AFTER)
    today = now.strftime("%Y-%m-%d")
    if stale and outcome is None and status.get("stale_warned_day") != today:
        hours = "?" if age is None else str(int(age.total_seconds() // 3600))
        await _report(bot, group_t("backup.stale", hours=hours))
        status["stale_warned_day"] = today
        _try_save_status(status)
    return outcome


async def backup_loop(bot: Bot | None) -> None:
    """The nightly backup, from BACKUP_HOUR_UTC on, once a day; with or without a bot.

    Runs on its own, not as part of the bot's polling, so a bot that stopped (a
    revoked token, say) does not take the backups with it.
    """
    if bot is None or settings.family_chat_id is None:
        log.warning("backups are kept on the server only: no bot or FAMILY_CHAT_ID")
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        try:
            await scheduled_tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed backup must not kill the loop
            log.warning("scheduled backup check failed", exc_info=True)
        await asyncio.sleep(CHECK_INTERVAL)


# --- console ------------------------------------------------------------------------------


def _extract(archive: Path, target: Path) -> Checked:
    """Unpack a checked archive into an empty directory — never over live data."""
    checked = verify_archive(archive)
    if target.exists() and any(target.iterdir()):
        raise BackupError("target directory is not empty")
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(target, members=list(_safe_members(tar)), filter="data")
    return checked


def main(argv: list[str]) -> int:
    """`python -m app.backup status | now | verify <archive> | extract <archive> <dir>`."""
    command = argv[0] if argv else "status"
    try:
        if command == "status":
            status = read_status()
            print(json.dumps(status, indent=2) if status else "no backup has run yet")
            for archive in local_archives():
                print(f"  {archive.name}  {archive.stat().st_size / 1024 / 1024:.1f} MB")
            age = newest_good_backup_age()
            print(
                f"newest local backup: {'none' if age is None else str(age).split('.')[0] + ' ago'}"
            )
            return 0 if age is not None and age <= STALE_AFTER else 1
        if command == "now":
            outcome = asyncio.run(run_backup(None, "console"))
            print(f"local: {outcome.local_file or outcome.local_error}")
            return 0 if outcome.local_file else 1
        if command == "verify" and len(argv) == 2:
            checked = verify_archive(Path(argv[1]))
            print(
                f"ok: {checked.vouchers} cards, {checked.images} pictures, "
                f"{len(checked.missing_images)} missing, revision {checked.revision}"
            )
            return 0 if not checked.missing_images else 2
        if command == "extract" and len(argv) == 3:
            checked = _extract(Path(argv[1]), Path(argv[2]))
            print(f"extracted {checked.vouchers} cards and {checked.images} pictures to {argv[2]}")
            return 0
    except BackupError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    print(main.__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

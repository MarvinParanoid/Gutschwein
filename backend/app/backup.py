"""Nightly backup into the family chat.

The whole state is one SQLite file plus the uploads directory, and the family chat
is a place both members already read every day — so it doubles as free off-site
storage. No object storage, no credentials, no second server.

The database is snapshotted through sqlite3's online backup API rather than copied:
a plain file copy taken while the app is writing can be a torn, unusable database.
"""

import asyncio
import logging
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import settings

log = logging.getLogger(__name__)

# Bots may upload up to 50 MB; stay clear of the edge.
MAX_UPLOAD_BYTES = 45 * 1024 * 1024
MARKER = ".last_backup"


def database_file() -> Path | None:
    """The SQLite file behind DATABASE_URL, if that is what we are running on."""
    url = settings.database_url
    if "sqlite" not in url:
        return None
    path = url.split("///", 1)[-1]
    return Path(path) if path else None


def _snapshot_database(source: Path, target: Path) -> None:
    """Consistent copy of a live database (sqlite's own backup API)."""
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(
        target
    ) as dst:
        src.backup(dst)


def _build_archive(workdir: Path, include_uploads: bool) -> tuple[Path, int, int]:
    """Pack the snapshot (and optionally the images). Returns path, files, bytes."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    archive = workdir / f"sparschwein-{stamp}.tar.gz"
    db = database_file()
    images = 0

    with tarfile.open(archive, "w:gz") as tar:
        if db is not None and db.exists():
            snapshot = workdir / "sparschwein.db"
            _snapshot_database(db, snapshot)
            tar.add(snapshot, arcname="sparschwein.db")
        if include_uploads and settings.upload_dir.exists():
            for image in sorted(settings.upload_dir.rglob("*")):
                if image.is_file():
                    relative = image.relative_to(settings.upload_dir)
                    tar.add(image, arcname=str(Path("uploads") / relative))
                    images += 1

    return archive, images, archive.stat().st_size


def create_archive(workdir: Path) -> tuple[Path, str]:
    """Archive plus a human summary; drops the images if the result is too big."""
    archive, images, size = _build_archive(workdir, include_uploads=True)
    if size > MAX_UPLOAD_BYTES:
        # Losing the images from one archive beats losing the backup entirely.
        archive.unlink(missing_ok=True)
        archive, images, size = _build_archive(workdir, include_uploads=False)
        note = (
            f"\n⚠️ Картинки не влезли в лимит Telegram ({MAX_UPLOAD_BYTES // 1024 // 1024} МБ) "
            "— в архиве только база. Фото есть в этом чате выше."
        )
    else:
        note = ""

    summary = f"{size / 1024 / 1024:.1f} МБ, картинок: {images}{note}"
    return archive, summary


async def send_backup(bot: Bot, reason: str) -> str:
    """Build and send a backup. Returns the summary line, raises on failure."""
    if settings.family_chat_id is None:
        raise RuntimeError("FAMILY_CHAT_ID не задан — некуда отправлять бэкап")

    with tempfile.TemporaryDirectory(prefix="sparschwein-backup-") as tmp:
        archive, summary = await asyncio.to_thread(create_archive, Path(tmp))
        stamp = datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC")
        await bot.send_document(
            settings.family_chat_id,
            FSInputFile(archive),
            caption=f"💾 Бэкап Sparschwein · {stamp}\n{summary}\n{reason}",
            disable_notification=True,
        )
    log.info("backup sent: %s", summary)
    return summary


def _marker_path() -> Path:
    return settings.data_dir / MARKER


def _already_done_today() -> bool:
    marker = _marker_path()
    if not marker.exists():
        return False
    return marker.read_text().strip() == datetime.now(UTC).strftime("%Y-%m-%d")


def _mark_done() -> None:
    _marker_path().write_text(datetime.now(UTC).strftime("%Y-%m-%d"))


def _seconds_until_next_run() -> float:
    now = datetime.now(UTC)
    target = now.replace(hour=settings.backup_hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def backup_loop(bot: Bot) -> None:
    """One backup per day. The marker file keeps restarts from resending."""
    if settings.family_chat_id is None:
        log.warning("backups disabled: FAMILY_CHAT_ID is not set")
        return

    while True:
        await asyncio.sleep(_seconds_until_next_run())
        try:
            if _already_done_today():
                continue
            await send_backup(bot, "по расписанию")
            _mark_done()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed backup must not kill the loop
            log.warning("scheduled backup failed", exc_info=True)

"""Housekeeping: images that no voucher points at.

Uploading is two-step — `POST /api/uploads` stores the file, the voucher is saved
with its id afterwards — so abandoning the form leaves a file nothing references.
Replacing or deleting a voucher removes its image right away; this sweeps up the
rest.

Two guards make deletion safe:
  * a grace period, because a file uploaded a minute ago may belong to a form that
    is still open;
  * the filename pattern, so only files this app generates can ever be removed.
"""

import asyncio
import logging
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import settings
from app.db import SessionLocal
from app.models import Voucher

log = logging.getLogger(__name__)

GRACE_SECONDS = 24 * 3600
SWEEP_INTERVAL = 24 * 3600
FIRST_SWEEP_DELAY = 300


async def cleanup_orphan_images(
    session: AsyncSession, grace_seconds: int = GRACE_SECONDS
) -> tuple[int, int]:
    """Delete unreferenced images older than the grace period. Returns (files, bytes)."""
    rows = await session.execute(
        select(Voucher.image_path).where(Voucher.image_path.is_not(None))
    )
    referenced = set(rows.scalars().all())

    root = settings.upload_dir
    if not root.exists():
        return 0, 0

    cutoff = time.time() - grace_seconds
    removed = freed = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in referenced or not storage.IMAGE_ID_RE.match(relative):
            continue
        stat = path.stat()
        if stat.st_mtime > cutoff:
            continue
        path.unlink(missing_ok=True)
        removed += 1
        freed += stat.st_size

    _drop_empty_month_dirs(root)
    if removed:
        log.info("cleanup removed %s orphan image(s), %s bytes", removed, freed)
    return removed, freed


def _drop_empty_month_dirs(root: Path) -> None:
    for directory in sorted(root.iterdir()):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


async def maintenance_loop() -> None:
    """Runs regardless of the bot: housekeeping is not a Telegram feature."""
    await asyncio.sleep(FIRST_SWEEP_DELAY)
    while True:
        try:
            async with SessionLocal() as session:
                await cleanup_orphan_images(session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let housekeeping kill the process
            log.warning("orphan image cleanup failed", exc_info=True)
        await asyncio.sleep(SWEEP_INTERVAL)

"""Housekeeping: images that no voucher points at, and credentials that expired.

Uploading is two-step — `POST /api/uploads` stores the file, the voucher is saved
with its id afterwards — so abandoning the form leaves a file nothing references.
Replacing or deleting a voucher leaves the old picture too: deleting it in the
request, before or after the commit, could take a picture that the database still
pointed at. This sweep is the only thing that ever deletes an image.

Three guards make deletion safe:
  * a grace period, because a file uploaded a minute ago may belong to a form that
    is still open;
  * the filename pattern, so only files this app generates can ever be removed;
  * the writer lock: the last "is anything pointing at it?" and the unlink happen
    inside one write transaction, and attaching a picture checks the file under
    the same lock (`routers.vouchers._claim_image`). A reference that appears
    between the scan and the unlink is therefore seen, and a file the sweep has
    deleted is refused by the attachment instead of being pointed at.

Sessions and login tokens are swept here too. Neither is ever cleaned up by the
paths that create them: a session lives ninety days and a login link ten minutes,
and after that the row stays forever, refused on every use but still taking up
space and still turning up in anything that reads the table.
"""

import asyncio
import logging
import time
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import settings
from app.db import SessionLocal, take_writer_lock
from app.models import LoginToken, Session, Voucher, utcnow

log = logging.getLogger(__name__)

GRACE_SECONDS = 24 * 3600
SWEEP_INTERVAL = 24 * 3600
FIRST_SWEEP_DELAY = 300
# Files decided per write transaction: bounds how long other writers wait.
DELETE_BATCH = 100


async def cleanup_orphan_images(
    session: AsyncSession, grace_seconds: int = GRACE_SECONDS
) -> tuple[int, int]:
    """Delete unreferenced images older than the grace period. Returns (files, bytes).

    The scan of the volume runs without any lock (and off the event loop); it only
    proposes candidates. Each batch is then decided under the writer lock, held
    for one query and a few unlinks — microseconds each, the files are a few MB.
    """
    root = settings.upload_dir
    if not root.exists():
        return 0, 0

    candidates = await asyncio.to_thread(_stale_images, root, time.time() - grace_seconds)
    rows = await session.execute(select(Voucher.image_path).where(Voucher.image_path.is_not(None)))
    referenced = set(rows.scalars().all())
    candidates = [c for c in candidates if c[0] not in referenced]

    removed = freed = 0
    for start in range(0, len(candidates), DELETE_BATCH):
        batch = candidates[start : start + DELETE_BATCH]
        await take_writer_lock(session)
        try:
            claimed = await session.execute(
                select(Voucher.image_path).where(
                    Voucher.image_path.in_([relative for relative, _path in batch])
                )
            )
            still_referenced = set(claimed.scalars().all())
            for relative, path in batch:
                if relative in still_referenced:
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    log.warning("cleanup could not remove %s", relative, exc_info=True)
                    continue
                removed += 1
                freed += size
        finally:
            # Nothing was written; ending the transaction is what releases the lock.
            await session.rollback()

    await asyncio.to_thread(_drop_empty_month_dirs, root)
    if removed:
        log.info("cleanup removed %s orphan image(s), %s bytes", removed, freed)
    return removed, freed


def _stale_images(root: Path, cutoff: float) -> list[tuple[str, Path]]:
    """Files with a name this app generates, untouched since before `cutoff`."""
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if storage.IMAGE_ID_RE.match(relative) and path.stat().st_mtime <= cutoff:
            found.append((relative, path))
    return found


def _drop_empty_month_dirs(root: Path) -> None:
    # This month's directory is where uploads are being written right now: an
    # upload creates it and then writes into it, and removing it in between would
    # fail that upload.
    current = utcnow().strftime("%Y-%m")
    for directory in sorted(root.iterdir()):
        if directory.is_dir() and directory.name != current and not any(directory.iterdir()):
            directory.rmdir()


async def cleanup_expired_credentials(session: AsyncSession) -> tuple[int, int]:
    """Drop dead sessions and spent login tokens. Returns (sessions, tokens).

    A used token is as dead as an expired one — single use is the whole point —
    so both go, and nothing here can lock anybody out: every row removed is one
    that `resolve_session` or `redeem_login_token` already refuses.
    """
    now = utcnow()
    sessions = await session.execute(delete(Session).where(Session.expires_at < now))
    tokens = await session.execute(
        delete(LoginToken).where(or_(LoginToken.expires_at < now, LoginToken.used_at.is_not(None)))
    )
    await session.commit()
    if sessions.rowcount or tokens.rowcount:
        log.info(
            "cleanup removed %s expired session(s) and %s spent login token(s)",
            sessions.rowcount,
            tokens.rowcount,
        )
    return sessions.rowcount, tokens.rowcount


async def maintenance_loop() -> None:
    """Runs regardless of the bot: housekeeping is not a Telegram feature."""
    await asyncio.sleep(FIRST_SWEEP_DELAY)
    while True:
        try:
            async with SessionLocal() as session:
                await cleanup_orphan_images(session)
                await cleanup_expired_credentials(session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let housekeeping kill the process
            log.warning("housekeeping sweep failed", exc_info=True)
        await asyncio.sleep(SWEEP_INTERVAL)

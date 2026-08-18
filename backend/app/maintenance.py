"""Housekeeping: images that no voucher points at, and credentials that expired.

Uploading is two-step — `POST /api/uploads` stores the file, the voucher is saved
with its id afterwards — so abandoning the form leaves a file nothing references.
Replacing or deleting a voucher removes its image right away; this sweeps up the
rest.

Two guards make deletion safe:
  * a grace period, because a file uploaded a minute ago may belong to a form that
    is still open;
  * the filename pattern, so only files this app generates can ever be removed.

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
from app.db import SessionLocal
from app.models import LoginToken, Session, Voucher, utcnow

log = logging.getLogger(__name__)

GRACE_SECONDS = 24 * 3600
SWEEP_INTERVAL = 24 * 3600
FIRST_SWEEP_DELAY = 300


async def cleanup_orphan_images(
    session: AsyncSession, grace_seconds: int = GRACE_SECONDS
) -> tuple[int, int]:
    """Delete unreferenced images older than the grace period. Returns (files, bytes)."""
    rows = await session.execute(select(Voucher.image_path).where(Voucher.image_path.is_not(None)))
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

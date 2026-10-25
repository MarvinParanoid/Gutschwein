"""Shared voucher helpers: lookup, event log, human-readable labels."""

import asyncio
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import barcode, storage
from app.expiry import default_expiry
from app.i18n import Message, default_language, t
from app.models import Comment, Event, EventKind, User, ValueKind, Voucher, utcnow

CENT = Decimal("0.01")


async def get_voucher_or_404(session: AsyncSession, voucher_id: int) -> Voucher:
    voucher = await session.get(Voucher, voucher_id)
    if voucher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.voucher_not_found"))
    return voucher


async def lock_voucher_or_404(session: AsyncSession, voucher_id: int) -> Voucher:
    """The voucher, read under its write lock: for anything computed from the balance.

    Reading first and writing a number computed from it lost money: two spends of 10
    on a 50 card both read 50, both wrote 40, and the log recorded 20 spent while the
    card dropped by 10. pysqlite opens no transaction for a SELECT, so nothing tied
    the read to the write.

    The no-op UPDATE is the first statement of the transaction, so the lock is taken
    before anything is read — SQLite's writer lock, a row lock on a server database.
    A concurrent request waits on it (busy_timeout) and then reads the committed
    result instead of a stale one. Everything up to the commit — the balance, its
    events, the status — lands or rolls back together, and the lock is held only
    that long: keep slow work (notifications, decoding) out of it.

    It sets `updated_at` to itself because a column left out of the SET gets its
    `onupdate` — and a request that turns out to change nothing would then reorder
    the lists that sort by it.
    """
    result = await session.execute(
        update(Voucher)
        .where(Voucher.id == voucher_id)
        .values(updated_at=Voucher.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.voucher_not_found"))
    # populate_existing: an object already in the session may predate the lock.
    voucher = await session.get(Voucher, voucher_id, populate_existing=True)
    assert voucher is not None  # the row was just updated inside this transaction
    return voucher


def record_event(
    session: AsyncSession,
    voucher: Voucher,
    actor: User | None,
    kind: EventKind,
    payload: dict | None = None,
) -> Event:
    event = Event(
        voucher_id=voucher.id,
        actor_id=actor.id if actor else None,
        kind=kind,
        payload=payload or {},
    )
    session.add(event)
    return event


async def comment_counts(session: AsyncSession, voucher_ids: list[int]) -> dict[int, int]:
    if not voucher_ids:
        return {}
    rows = await session.execute(
        select(Comment.voucher_id, func.count())
        .where(Comment.voucher_id.in_(voucher_ids))
        .group_by(Comment.voucher_id)
    )
    return dict(rows.all())


def apply_expiry_rule(voucher: Voucher) -> bool:
    """Fill in the shop's default expiry when the card does not state one.

    Counted from the activation date — `valid_from` if someone knows it, otherwise
    the day the card was added. A date the user typed is never touched.
    """
    if voucher.valid_until is not None or not voucher.merchant:
        return False
    activated = voucher.valid_from or utcnow().date()
    guess = default_expiry(voucher.merchant, activated)
    if guess is None:
        return False
    voucher.valid_until = guess
    voucher.expiry_estimated = True
    return True


async def attach_barcode(voucher: Voucher) -> None:
    """Read the code out of the attached picture.

    Never overwrites a code a human typed — the screenshot is evidence, not
    authority. Decoding a 1080p screenshot (with the upscale retry) takes long
    enough to be worth a thread.
    """
    if voucher.image_path and not storage.absolute_path(voucher.image_path).is_file():
        return
    apply_barcode(voucher, await read_barcode(voucher.image_path))


async def read_barcode(image_path: str | None) -> barcode.Decoded | None:
    """The slow half of `attach_barcode`: decode the picture, touch no voucher.

    Split out so a caller that locks the voucher can decode first and hold the lock
    only for `apply_barcode`.
    """
    if not image_path:
        return None
    path = storage.absolute_path(image_path)
    if not path.is_file():
        return None
    return await asyncio.to_thread(barcode.decode, path.read_bytes())


def apply_barcode(voucher: Voucher, found: barcode.Decoded | None) -> None:
    """The quick half: record what `read_barcode` found on the voucher."""
    voucher.barcode_format = found.format if found else None
    if found and not voucher.code:
        voucher.code = found.text[:128]


def format_amount(value: Decimal) -> str:
    """Money for humans: "10", "12.5", never Decimal.normalize()'s "1E+1".

    normalize() turns 10 into 1E+1 — correct arithmetic, nonsense in a chat message.
    """
    text = format(value.quantize(CENT), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def value_label(voucher: Voucher, language: str | None = None) -> str:
    if voucher.value_kind == ValueKind.amount and voucher.value_amount is not None:
        return f"{format_amount(voucher.value_amount)} {voucher.currency}"
    if voucher.value_kind == ValueKind.percent and voucher.value_amount is not None:
        return f"-{format_amount(voucher.value_amount)}%"
    return voucher.title or t("label.voucher", language or default_language())


def voucher_label(voucher: Voucher, language: str | None = None) -> str:
    language = language or default_language()
    parts = [p for p in (voucher.merchant, value_label(voucher, language)) if p]
    return " · ".join(parts) or t("label.voucher_numbered", language, id=voucher.id)

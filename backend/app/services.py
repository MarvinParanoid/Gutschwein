"""Shared voucher helpers: lookup, event log, human-readable labels."""

import asyncio
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import barcode, storage
from app.models import Comment, Event, EventKind, User, ValueKind, Voucher

CENT = Decimal("0.01")


async def get_voucher_or_404(session: AsyncSession, voucher_id: int) -> Voucher:
    voucher = await session.get(Voucher, voucher_id)
    if voucher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Купон не найден")
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


async def attach_barcode(voucher: Voucher) -> None:
    """Read the code out of the attached picture.

    Never overwrites a code a human typed — the screenshot is evidence, not
    authority. Decoding a 1080p screenshot (with the upscale retry) takes long
    enough to be worth a thread.
    """
    if not voucher.image_path:
        voucher.barcode_format = None
        return

    path = storage.absolute_path(voucher.image_path)
    if not path.is_file():
        return
    found = await asyncio.to_thread(barcode.decode, path.read_bytes())
    voucher.barcode_format = found.format if found else None
    if found and not voucher.code:
        voucher.code = found.text[:128]


def format_amount(value: Decimal) -> str:
    """Money for humans: "10", "12.5", never Decimal.normalize()'s "1E+1".

    normalize() turns 10 into 1E+1 — correct arithmetic, nonsense in a chat message.
    """
    text = format(value.quantize(CENT), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def value_label(voucher: Voucher) -> str:
    if voucher.value_kind == ValueKind.amount and voucher.value_amount is not None:
        return f"{format_amount(voucher.value_amount)} {voucher.currency}"
    if voucher.value_kind == ValueKind.percent and voucher.value_amount is not None:
        return f"-{format_amount(voucher.value_amount)}%"
    return voucher.title or "купон"


def voucher_label(voucher: Voucher) -> str:
    parts = [p for p in (voucher.merchant, value_label(voucher)) if p]
    return " · ".join(parts) or f"Купон #{voucher.id}"

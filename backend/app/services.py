"""Shared voucher helpers: lookup, event log, human-readable labels."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Event, EventKind, User, ValueKind, Voucher


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


def value_label(voucher: Voucher) -> str:
    if voucher.value_kind == ValueKind.amount and voucher.value_amount is not None:
        amount = voucher.value_amount.normalize()
        return f"{amount} {voucher.currency}"
    if voucher.value_kind == ValueKind.percent and voucher.value_amount is not None:
        return f"-{voucher.value_amount.normalize()}%"
    return voucher.title or "купон"


def voucher_label(voucher: Voucher) -> str:
    parts = [p for p in (voucher.merchant, value_label(voucher)) if p]
    return " · ".join(parts) or f"Купон #{voucher.id}"

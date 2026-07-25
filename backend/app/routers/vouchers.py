from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.auth import CurrentUser
from app.db import get_session
from app.models import (
    Comment,
    Event,
    EventKind,
    User,
    ValueKind,
    Voucher,
    VoucherStatus,
    utcnow,
)
from app.notify import notify
from app.schemas import (
    BalanceUpdate,
    CommentCreate,
    CommentOut,
    CountsOut,
    EventOut,
    MerchantStat,
    StatsOut,
    VoucherCreate,
    VoucherOut,
    VoucherUpdate,
)
from app.services import (
    comment_counts,
    format_amount,
    get_voucher_or_404,
    record_event,
    voucher_label,
)
from app.stats import collect_stats

router = APIRouter(prefix="/api/vouchers", tags=["vouchers"])

Session = Annotated[AsyncSession, Depends(get_session)]
StatusFilter = Literal["active", "draft", "used", "archived", "all"]


async def _serialize(session: AsyncSession, vouchers: list[Voucher]) -> list[VoucherOut]:
    counts = await comment_counts(session, [v.id for v in vouchers])
    out = []
    for voucher in vouchers:
        item = VoucherOut.model_validate(voucher)
        item.comments_count = counts.get(voucher.id, 0)
        out.append(item)
    return out


async def _serialize_one(session: AsyncSession, voucher: Voucher) -> VoucherOut:
    return (await _serialize(session, [voucher]))[0]


def _resolve_image(image_id: str | None) -> str | None:
    if image_id is None:
        return None
    if not storage.absolute_path(image_id).is_file():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Изображение не найдено")
    return image_id


@router.get("", response_model=list[VoucherOut])
async def list_vouchers(
    user: CurrentUser,
    session: Session,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = "active",
    q: Annotated[str | None, Query(max_length=128)] = None,
    merchant: Annotated[str | None, Query(max_length=128)] = None,
) -> list[VoucherOut]:
    stmt = select(Voucher)
    if status_filter != "all":
        stmt = stmt.where(Voucher.status == VoucherStatus(status_filter))
    if merchant:
        stmt = stmt.where(Voucher.merchant == merchant)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Voucher.merchant.ilike(pattern),
                Voucher.title.ilike(pattern),
                Voucher.code.ilike(pattern),
                Voucher.conditions.ilike(pattern),
                Voucher.notes.ilike(pattern),
            )
        )

    if status_filter in ("active", "all"):
        # Soonest expiry first; vouchers without a deadline sink to the bottom.
        stmt = stmt.order_by(
            Voucher.valid_until.is_(None), Voucher.valid_until, Voucher.created_at.desc()
        )
    else:
        stmt = stmt.order_by(Voucher.updated_at.desc())

    vouchers = list((await session.execute(stmt)).unique().scalars().all())
    return await _serialize(session, vouchers)


@router.get("/stats", response_model=StatsOut)
async def stats(user: CurrentUser, session: Session) -> StatsOut:
    return await collect_stats(session)


@router.get("/counts", response_model=CountsOut)
async def counts(user: CurrentUser, session: Session) -> CountsOut:
    rows = await session.execute(
        select(Voucher.status, func.count(), func.coalesce(func.sum(Voucher.balance_amount), 0))
        .group_by(Voucher.status)
    )
    result = CountsOut()
    for status_value, count, balance in rows.all():
        setattr(result, VoucherStatus(status_value).value, count)
        if status_value == VoucherStatus.archived:
            result.archived_balance = Decimal(balance or 0)
    return result


@router.get("/merchants/stats", response_model=list[MerchantStat])
async def merchant_stats(
    user: CurrentUser,
    session: Session,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = "active",
) -> list[MerchantStat]:
    """Shops for the chip row, most-used first.

    Frequency comes from the event log rather than a counter we maintain: every
    payment is already recorded as a `balance_updated` event.
    """
    stmt = select(
        Voucher.merchant,
        func.count(),
        func.coalesce(func.sum(Voucher.balance_amount), 0),
    ).where(Voucher.merchant != "")
    if status_filter != "all":
        stmt = stmt.where(Voucher.status == VoucherStatus(status_filter))
    rows = (await session.execute(stmt.group_by(Voucher.merchant))).all()

    uses_rows = await session.execute(
        select(Voucher.merchant, func.count())
        .join(Event, Event.voucher_id == Voucher.id)
        .where(Event.kind == EventKind.balance_updated, Voucher.merchant != "")
        .group_by(Voucher.merchant)
    )
    uses = dict(uses_rows.all())

    stats = [
        MerchantStat(
            merchant=merchant,
            count=count,
            balance=Decimal(balance or 0),
            uses=uses.get(merchant, 0),
        )
        for merchant, count, balance in rows
    ]
    # Regulars float up on their own; one-off shops sink to the end of the row.
    stats.sort(key=lambda s: (-s.uses, -s.count, s.merchant.lower()))
    return stats


@router.get("/merchants", response_model=list[str])
async def list_merchants(user: CurrentUser, session: Session) -> list[str]:
    """Distinct merchant names, for autocomplete in the form."""
    rows = await session.execute(
        select(Voucher.merchant)
        .where(Voucher.merchant != "")
        .distinct()
        .order_by(Voucher.merchant)
    )
    return list(rows.scalars().all())


@router.post("", response_model=VoucherOut, status_code=status.HTTP_201_CREATED)
async def create_voucher(
    user: CurrentUser, session: Session, payload: VoucherCreate
) -> VoucherOut:
    data = payload.model_dump(exclude={"image_id"})
    voucher = Voucher(
        **data, image_path=_resolve_image(payload.image_id), created_by_id=user.id
    )
    # A gift card starts out unspent, so its balance equals the face value.
    if voucher.value_kind == ValueKind.amount and voucher.value_amount is not None:
        voucher.balance_amount = voucher.value_amount
    session.add(voucher)
    await session.flush()
    record_event(session, voucher, user, EventKind.created)
    await session.commit()
    await session.refresh(voucher)

    if voucher.status == VoucherStatus.active:
        await notify(
            f"🐷 {user.display_name} добавил купон: <b>{voucher_label(voucher)}</b>"
        )
    return await _serialize_one(session, voucher)


@router.get("/{voucher_id}", response_model=VoucherOut)
async def get_voucher(user: CurrentUser, session: Session, voucher_id: int) -> VoucherOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    return await _serialize_one(session, voucher)


@router.patch("/{voucher_id}", response_model=VoucherOut)
async def update_voucher(
    user: CurrentUser, session: Session, voucher_id: int, payload: VoucherUpdate
) -> VoucherOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    changes = payload.model_dump(exclude_unset=True)

    image_id = changes.pop("image_id", ...)
    changed_fields = []
    previous_value = voucher.value_amount
    for field, value in changes.items():
        if getattr(voucher, field) != value:
            setattr(voucher, field, value)
            changed_fields.append(field)

    # Correcting the face value of an untouched gift card should move the balance
    # with it; a partly spent one keeps whatever is left.
    if (
        "value_amount" in changed_fields
        and "balance_amount" not in changes
        and voucher.value_kind == ValueKind.amount
        and voucher.balance_amount == previous_value
    ):
        voucher.balance_amount = voucher.value_amount

    if image_id is not ...:
        old = voucher.image_path
        voucher.image_path = _resolve_image(image_id)
        if old != voucher.image_path:
            record_event(session, voucher, user, EventKind.image_replaced)
            storage.delete(old)

    if changed_fields:
        record_event(
            session, voucher, user, EventKind.updated, {"fields": changed_fields}
        )
    await session.commit()
    await session.refresh(voucher)
    return await _serialize_one(session, voucher)


async def _transition(
    session: AsyncSession,
    voucher: Voucher,
    user: User,
    new_status: VoucherStatus,
    kind: EventKind,
) -> None:
    voucher.status = new_status
    if new_status == VoucherStatus.used:
        voucher.used_at = utcnow()
        voucher.used_by_id = user.id
    elif kind == EventKind.unused:
        voucher.used_at = None
        voucher.used_by_id = None
    voucher.archived_at = utcnow() if new_status == VoucherStatus.archived else None
    record_event(session, voucher, user, kind)
    await session.commit()
    await session.refresh(voucher)


@router.post("/{voucher_id}/use", response_model=VoucherOut)
async def mark_used(user: CurrentUser, session: Session, voucher_id: int) -> VoucherOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    if voucher.status == VoucherStatus.used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Купон уже отмечен использованным")
    # "Used up" on a gift card means nothing is left on it.
    if voucher.balance_amount is not None and voucher.balance_amount > 0:
        record_event(
            session,
            voucher,
            user,
            EventKind.balance_updated,
            {"spent": str(voucher.balance_amount), "remaining": "0", "note": ""},
        )
        voucher.balance_amount = Decimal("0.00")
    await _transition(session, voucher, user, VoucherStatus.used, EventKind.used)
    await notify(
        f"✅ {user.display_name} использовал купон: <b>{voucher_label(voucher)}</b>"
    )
    return await _serialize_one(session, voucher)


CENT = Decimal("0.01")


@router.post("/{voucher_id}/balance", response_model=VoucherOut)
async def update_balance(
    user: CurrentUser, session: Session, voucher_id: int, payload: BalanceUpdate
) -> VoucherOut:
    """Write down what is left on a gift card after paying with it.

    The caller sends either what was spent or the remaining balance printed on
    the receipt. Corrections need no special path: sending `remaining` again
    overwrites the number, and the event log keeps both attempts.
    """
    voucher = await get_voucher_or_404(session, voucher_id)
    if voucher.value_kind != ValueKind.amount:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Остаток есть только у купонов на сумму"
        )

    current = (
        voucher.balance_amount
        if voucher.balance_amount is not None
        else voucher.value_amount
    )
    if current is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "У купона не указан номинал — сначала заполните его"
        )

    if payload.spent is not None:
        if payload.spent > current:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Нельзя списать {format_amount(payload.spent)} — "
                f"на купоне {format_amount(current)} {voucher.currency}",
            )
        new_balance = current - payload.spent
    else:
        new_balance = payload.remaining
        if voucher.value_amount is not None and new_balance > voucher.value_amount:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Остаток больше номинала ({format_amount(voucher.value_amount)} "
                f"{voucher.currency}) — "
                "поправьте номинал в купоне",
            )

    new_balance = new_balance.quantize(CENT)
    delta = (current - new_balance).quantize(CENT)
    voucher.balance_amount = new_balance
    record_event(
        session,
        voucher,
        user,
        EventKind.balance_updated,
        {"spent": str(delta), "remaining": str(new_balance), "note": payload.note},
    )

    emptied = new_balance == 0 and voucher.status != VoucherStatus.used
    if emptied:
        voucher.status = VoucherStatus.used
        voucher.used_at = utcnow()
        voucher.used_by_id = user.id
        record_event(session, voucher, user, EventKind.used, {"reason": "balance_empty"})

    await session.commit()
    await session.refresh(voucher)

    label = voucher_label(voucher)
    if emptied:
        await notify(f"💳 {user.display_name} потратил <b>{label}</b> до конца")
    elif delta > 0:
        await notify(
            f"💳 {user.display_name}: −{format_amount(delta)} {voucher.currency} "
            f"с <b>{label}</b>, осталось {format_amount(new_balance)} {voucher.currency}"
        )
    else:
        await notify(
            f"💳 {user.display_name} поправил остаток <b>{label}</b>: "
            f"{format_amount(new_balance)} {voucher.currency}"
        )
    return await _serialize_one(session, voucher)


@router.post("/{voucher_id}/activate", response_model=VoucherOut)
async def activate_draft(
    user: CurrentUser, session: Session, voucher_id: int
) -> VoucherOut:
    """Promote a draft (usually created from a photo sent to the bot) to active."""
    voucher = await get_voucher_or_404(session, voucher_id)
    if voucher.status != VoucherStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Это не черновик")
    await _transition(session, voucher, user, VoucherStatus.active, EventKind.published)
    await notify(
        f"🐷 {user.display_name} добавил купон: <b>{voucher_label(voucher)}</b>"
    )
    return await _serialize_one(session, voucher)


@router.post("/{voucher_id}/unuse", response_model=VoucherOut)
async def mark_unused(user: CurrentUser, session: Session, voucher_id: int) -> VoucherOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    await _transition(session, voucher, user, VoucherStatus.active, EventKind.unused)
    return await _serialize_one(session, voucher)


@router.post("/{voucher_id}/archive", response_model=VoucherOut)
async def archive(user: CurrentUser, session: Session, voucher_id: int) -> VoucherOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    await _transition(session, voucher, user, VoucherStatus.archived, EventKind.archived)
    return await _serialize_one(session, voucher)


@router.post("/{voucher_id}/restore", response_model=VoucherOut)
async def restore(user: CurrentUser, session: Session, voucher_id: int) -> VoucherOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    await _transition(session, voucher, user, VoucherStatus.active, EventKind.restored)
    return await _serialize_one(session, voucher)


@router.delete("/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voucher(user: CurrentUser, session: Session, voucher_id: int) -> None:
    """Hard delete. Archiving is the soft option; this one really removes it."""
    voucher = await get_voucher_or_404(session, voucher_id)
    image_path = voucher.image_path
    await session.delete(voucher)
    await session.commit()
    storage.delete(image_path)


@router.get("/{voucher_id}/comments", response_model=list[CommentOut])
async def list_comments(
    user: CurrentUser, session: Session, voucher_id: int
) -> list[CommentOut]:
    await get_voucher_or_404(session, voucher_id)
    rows = await session.execute(
        select(Comment)
        .where(Comment.voucher_id == voucher_id)
        .order_by(Comment.created_at, Comment.id)
    )
    return [CommentOut.model_validate(c) for c in rows.unique().scalars().all()]


@router.post(
    "/{voucher_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    user: CurrentUser, session: Session, voucher_id: int, payload: CommentCreate
) -> CommentOut:
    voucher = await get_voucher_or_404(session, voucher_id)
    comment = Comment(voucher_id=voucher.id, author_id=user.id, text=payload.text)
    session.add(comment)
    record_event(
        session, voucher, user, EventKind.commented, {"preview": payload.text[:120]}
    )
    await session.commit()
    await session.refresh(comment)
    await notify(
        f"💬 {user.display_name} к купону <b>{voucher_label(voucher)}</b>: {payload.text[:200]}"
    )
    return CommentOut.model_validate(comment)


@router.delete(
    "/{voucher_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_comment(
    user: CurrentUser, session: Session, voucher_id: int, comment_id: int
) -> None:
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.voucher_id != voucher_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комментарий не найден")
    if comment.author_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Удалять можно только свои комментарии"
        )
    await session.delete(comment)
    await session.commit()


@router.get("/{voucher_id}/events", response_model=list[EventOut])
async def list_events(
    user: CurrentUser, session: Session, voucher_id: int
) -> list[EventOut]:
    await get_voucher_or_404(session, voucher_id)
    rows = await session.execute(
        select(Event)
        .where(Event.voucher_id == voucher_id)
        # id breaks ties: server_default=now() has second granularity, so several
        # events from one request share a timestamp.
        .order_by(Event.created_at.desc(), Event.id.desc())
    )
    return [EventOut.model_validate(e) for e in rows.unique().scalars().all()]

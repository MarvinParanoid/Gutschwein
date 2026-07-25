"""Family spending statistics.

Every payment is already in the event log as a `balance_updated` event carrying
`{spent, remaining}`, so nothing needs to be counted twice or denormalised. The
sums are computed in Python rather than SQL because the amounts live inside a JSON
payload — and for a family's worth of vouchers the row count is trivial.

Sums are *net*: a correction that puts money back on a card (a negative delta)
reduces the total, which is what "how much actually left the cards" means.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, EventKind, User, Voucher, VoucherStatus, utcnow
from app.schemas import MemberSpend, MerchantSpend, MonthSpend, StatsOut

EXPIRING_SOON_DAYS = 30
TOP_MERCHANTS = 8
MONTHS_BACK = 6


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _shift_month(anchor: date, months: int) -> date:
    """First day of the month `months` before `anchor` (may be negative)."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


async def collect_stats(session: AsyncSession) -> StatsOut:
    today = utcnow().date()
    stats = StatsOut(expiring_soon_days=EXPIRING_SOON_DAYS)

    # --- what is on the cards right now ---
    active_rows = await session.execute(
        select(Voucher.merchant, Voucher.balance_amount, Voucher.valid_until).where(
            Voucher.status == VoucherStatus.active
        )
    )
    on_cards_by_merchant: dict[str, Decimal] = {}
    soon = today + timedelta(days=EXPIRING_SOON_DAYS)
    for merchant, balance, valid_until in active_rows.all():
        amount = Decimal(balance or 0)
        stats.cards_active += 1
        stats.on_cards += amount
        if merchant:
            on_cards_by_merchant[merchant] = on_cards_by_merchant.get(merchant, Decimal(0)) + amount
        if valid_until is not None and amount > 0:
            if valid_until < today:
                stats.expired_balance += amount
            elif valid_until <= soon:
                stats.expiring_soon += amount

    archived = await session.execute(
        select(func.coalesce(func.sum(Voucher.balance_amount), 0)).where(
            Voucher.status == VoucherStatus.archived
        )
    )
    stats.archived_balance = Decimal(archived.scalar() or 0)

    currency = await session.execute(
        select(Voucher.currency).where(Voucher.currency != "").limit(1)
    )
    stats.currency = currency.scalar() or "EUR"

    # --- what has been spent, from the event log ---
    spend_rows = await session.execute(
        select(Event.created_at, Event.payload, Voucher.merchant, User)
        .join(Voucher, Voucher.id == Event.voucher_id)
        .outerjoin(User, User.id == Event.actor_id)
        .where(Event.kind == EventKind.balance_updated)
    )

    spent_by_merchant: dict[str, Decimal] = {}
    spent_by_member: dict[str, list] = {}
    spent_by_month: dict[str, Decimal] = {}
    this_month = _month_key(today)
    prev_month = _month_key(_shift_month(today, -1))

    for created_at, payload, merchant, actor in spend_rows.all():
        amount = Decimal(str(payload.get("spent", "0") or "0"))
        if amount == 0:
            continue
        stats.spent_total += amount

        month = _month_key(created_at.date())
        spent_by_month[month] = spent_by_month.get(month, Decimal(0)) + amount
        if month == this_month:
            stats.spent_this_month += amount
        elif month == prev_month:
            stats.spent_prev_month += amount

        if merchant:
            spent_by_merchant[merchant] = spent_by_merchant.get(merchant, Decimal(0)) + amount

        name = actor.display_name if actor is not None else "Кто-то"
        entry = spent_by_member.setdefault(name, [Decimal(0), 0])
        entry[0] += amount
        entry[1] += 1

    merchants = set(spent_by_merchant) | set(on_cards_by_merchant)
    stats.by_merchant = sorted(
        (
            MerchantSpend(
                merchant=name,
                spent=spent_by_merchant.get(name, Decimal(0)),
                on_cards=on_cards_by_merchant.get(name, Decimal(0)),
            )
            for name in merchants
        ),
        key=lambda m: (-m.spent, -m.on_cards, m.merchant.lower()),
    )[:TOP_MERCHANTS]

    stats.by_member = sorted(
        (
            MemberSpend(name=name, spent=spent, payments=payments)
            for name, (spent, payments) in spent_by_member.items()
        ),
        key=lambda m: -m.spent,
    )

    # A continuous month axis: gaps must render as zero, not disappear.
    stats.monthly = [
        MonthSpend(
            month=key,
            spent=spent_by_month.get(key, Decimal(0)),
        )
        for key in (
            _month_key(_shift_month(today, offset))
            for offset in range(-(MONTHS_BACK - 1), 1)
        )
    ]
    return stats

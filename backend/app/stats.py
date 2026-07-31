"""Family spending statistics.

Every payment is already in the event log as a `balance_updated` event carrying
`{spent, remaining}`, so nothing needs to be counted twice or denormalised. The
sums are computed in Python rather than SQL because the amounts live inside a JSON
payload — and for a family's worth of vouchers the row count is trivial.

Sums are *net*: a correction that puts money back on a card (a negative delta)
reduces the total, which is what "how much actually left the cards" means.

Every sum is per currency. A card's money is only spendable at its own shops, so
adding a złoty card to a euro one produces a number that means nothing — and used to:
the page took the currency off whichever voucher the database returned first and
labelled the mixed total with it. Nothing is converted either; that would need a rate,
a network, and a story for what a past month's total means when the rate has moved.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import default_language, t
from app.models import Event, EventKind, User, Voucher, VoucherStatus, utcnow
from app.schemas import CurrencyStats, MemberSpend, MerchantSpend, MonthSpend, StatsOut

EXPIRING_SOON_DAYS = 30
TOP_MERCHANTS = 8
MONTHS_BACK = 6
# What an empty family gets, so the page has something to render. Same default as
# a new voucher's currency.
FALLBACK_CURRENCY = "EUR"


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _shift_month(anchor: date, months: int) -> date:
    """First day of the month `months` before `anchor` (may be negative)."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


async def collect_stats(session: AsyncSession, language: str | None = None) -> StatsOut:
    language = language or default_language()
    today = utcnow().date()
    stats = StatsOut(expiring_soon_days=EXPIRING_SOON_DAYS)

    blocks: dict[str, CurrencyStats] = {}
    # How many cards each currency has, in any status: the order of the blocks.
    cards_seen: dict[str, int] = defaultdict(int)
    on_cards_by_merchant: dict[str, dict[str, Decimal]] = defaultdict(dict)
    spent_by_merchant: dict[str, dict[str, Decimal]] = defaultdict(dict)
    spent_by_member: dict[str, dict[str, list]] = defaultdict(dict)
    spent_by_month: dict[str, dict[str, Decimal]] = defaultdict(dict)

    def block(currency: str) -> CurrencyStats:
        # A card saved before the currency field was checked can hold an empty
        # string; it belongs with the default rather than in a nameless group.
        code = currency or FALLBACK_CURRENCY
        return blocks.setdefault(code, CurrencyStats(currency=code))

    # --- what is on the cards right now ---
    active_rows = await session.execute(
        select(
            Voucher.currency,
            Voucher.merchant,
            Voucher.balance_amount,
            Voucher.valid_until,
            Voucher.balance_uncertain,
        ).where(Voucher.status == VoucherStatus.active)
    )
    soon = today + timedelta(days=EXPIRING_SOON_DAYS)
    for currency, merchant, balance, valid_until, uncertain in active_rows.all():
        amount = Decimal(balance or 0)
        here = block(currency)
        here.cards_active += 1
        if uncertain:
            # Kept out of every "you have" figure: money you are unsure about is
            # not money you can plan with. It gets its own line instead.
            here.uncertain_balance += amount
            here.cards_uncertain += 1
            continue
        here.on_cards += amount
        if merchant:
            per_merchant = on_cards_by_merchant[here.currency]
            per_merchant[merchant] = per_merchant.get(merchant, Decimal(0)) + amount
        if valid_until is not None and amount > 0:
            if valid_until < today:
                here.expired_balance += amount
            elif valid_until <= soon:
                here.expiring_soon += amount

    archived = await session.execute(
        select(Voucher.currency, func.coalesce(func.sum(Voucher.balance_amount), 0))
        .where(Voucher.status == VoucherStatus.archived)
        .group_by(Voucher.currency)
    )
    for currency, balance in archived.all():
        block(currency).archived_balance = Decimal(balance or 0)

    all_currencies = await session.execute(
        select(Voucher.currency, func.count()).group_by(Voucher.currency)
    )
    for currency, count in all_currencies.all():
        cards_seen[currency or FALLBACK_CURRENCY] = count
        block(currency)

    # --- what has been spent, from the event log ---
    spend_rows = await session.execute(
        select(Event.created_at, Event.payload, Voucher.currency, Voucher.merchant, User)
        .join(Voucher, Voucher.id == Event.voucher_id)
        .outerjoin(User, User.id == Event.actor_id)
        .where(Event.kind == EventKind.balance_updated)
    )

    this_month = _month_key(today)
    prev_month = _month_key(_shift_month(today, -1))

    for created_at, payload, currency, merchant, actor in spend_rows.all():
        amount = Decimal(str(payload.get("spent", "0") or "0"))
        if amount == 0:
            continue
        here = block(currency)
        here.spent_total += amount

        month = _month_key(created_at.date())
        per_month = spent_by_month[here.currency]
        per_month[month] = per_month.get(month, Decimal(0)) + amount
        if month == this_month:
            here.spent_this_month += amount
        elif month == prev_month:
            here.spent_prev_month += amount

        if merchant:
            per_merchant = spent_by_merchant[here.currency]
            per_merchant[merchant] = per_merchant.get(merchant, Decimal(0)) + amount

        name = actor.display_name if actor is not None else t("label.someone", language)
        entry = spent_by_member[here.currency].setdefault(name, [Decimal(0), 0])
        entry[0] += amount
        entry[1] += 1

    # A family with no cards still opens the screen, and an empty page has nothing
    # to say. One block of zeroes, filled in below like any other.
    if not blocks:
        block(FALLBACK_CURRENCY)

    months = [
        _month_key(_shift_month(today, offset)) for offset in range(-(MONTHS_BACK - 1), 1)
    ]
    for currency, here in blocks.items():
        spent = spent_by_merchant[currency]
        on_cards = on_cards_by_merchant[currency]
        here.by_merchant = sorted(
            (
                MerchantSpend(
                    merchant=name,
                    spent=spent.get(name, Decimal(0)),
                    on_cards=on_cards.get(name, Decimal(0)),
                )
                for name in set(spent) | set(on_cards)
            ),
            key=lambda m: (-m.spent, -m.on_cards, m.merchant.lower()),
        )[:TOP_MERCHANTS]

        here.by_member = sorted(
            (
                MemberSpend(name=name, spent=amount, payments=payments)
                for name, (amount, payments) in spent_by_member[currency].items()
            ),
            key=lambda m: -m.spent,
        )

        # A continuous month axis: gaps must render as zero, not disappear.
        here.monthly = [
            MonthSpend(month=key, spent=spent_by_month[currency].get(key, Decimal(0)))
            for key in months
        ]

    stats.currencies = sorted(
        blocks.values(), key=lambda b: (-cards_seen[b.currency], b.currency)
    )
    return stats

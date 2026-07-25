"""Adding a card by writing "Rewe 50".

Buying a gift card is two actions: take a screenshot, then say the shop and the
amount. So the bot accepts exactly that — as a photo caption, or as a message that
completes the draft the photo created.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventKind, User, ValueKind, Voucher, VoucherStatus
from app.services import record_event

# A bare number, optionally with two decimals: "50", "12.50", "12,50".
AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{1,6}(?:[.,]\d{1,2})?)(?![\d.,])")
CURRENCY_WORDS = {"eur", "евро", "€", "e", "у.е.", "уе"}
MAX_AMOUNT = Decimal("100000")


@dataclass(frozen=True)
class QuickAdd:
    merchant: str | None = None
    amount: Decimal | None = None

    @property
    def is_empty(self) -> bool:
        return self.merchant is None and self.amount is None


def _clean(text: str) -> str:
    return text.strip(" \t\n·-–—:,.;").strip()


def _drop_currency(text: str) -> str:
    words = [w for w in _clean(text).split() if w.lower().strip(".") not in CURRENCY_WORDS]
    return " ".join(words)


def parse_quick_add(text: str) -> QuickAdd:
    """Split "Jet Tankstelle 60 EUR" into a shop and an amount.

    The amount is the last standalone number: shop names may contain digits far
    more plausibly at the front ("5 Sterne") than at the end.
    """
    if not text or not text.strip():
        return QuickAdd()

    matches = list(AMOUNT_RE.finditer(text))
    if not matches:
        merchant = _drop_currency(text)
        return QuickAdd(merchant=merchant[:128] or None)

    match = matches[-1]
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return QuickAdd(merchant=_drop_currency(text)[:128] or None)

    if amount <= 0 or amount > MAX_AMOUNT:
        amount = None

    before = _drop_currency(text[: match.start()])
    after = _drop_currency(text[match.end() :])
    # "Rewe 50" puts the name first; "50 Rewe" is unusual but unambiguous.
    merchant = before or after
    return QuickAdd(merchant=merchant[:128] or None, amount=amount)


async def find_pending_draft(session: AsyncSession, user: User) -> Voucher | None:
    """The draft this member most recently created from a photo."""
    rows = await session.execute(
        select(Voucher)
        .where(Voucher.status == VoucherStatus.draft, Voucher.created_by_id == user.id)
        .order_by(Voucher.created_at.desc(), Voucher.id.desc())
        .limit(1)
    )
    return rows.unique().scalars().first()


async def apply_quick_add(
    session: AsyncSession, user: User, voucher: Voucher, parsed: QuickAdd
) -> bool:
    """Fill a draft in place. Returns True when it became an active card.

    A card is complete once it has a shop and an amount; until then it stays a
    draft so nothing half-entered shows up as spendable money.
    """
    changed = []
    if parsed.merchant:
        voucher.merchant = parsed.merchant
        changed.append("merchant")
    if parsed.amount is not None:
        voucher.value_kind = ValueKind.amount
        voucher.value_amount = parsed.amount
        voucher.balance_amount = parsed.amount
        changed.append("value_amount")

    if changed:
        record_event(session, voucher, user, EventKind.updated, {"fields": changed})

    complete = bool(voucher.merchant) and voucher.value_amount is not None
    if complete and voucher.status == VoucherStatus.draft:
        voucher.status = VoucherStatus.active
        record_event(session, voucher, user, EventKind.published, {"source": "bot"})

    await session.commit()
    await session.refresh(voucher)
    return complete

"""Weekly summary into the family chat.

The failure mode of this app is silence: cards sit unopened until they expire. So
once a week the bot says how much is lying around and what is about to burn — the
expiring money first, because that is the part you can still act on.

Nothing is sent when there is nothing to act on; a weekly "you have no cards" is
just noise that trains people to ignore the bot.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.i18n import group_t
from app.models import Event, EventKind, Voucher, VoucherStatus, utcnow
from app.schemas import CurrencyStats
from app.services import format_amount
from app.stats import FALLBACK_CURRENCY, collect_stats

log = logging.getLogger(__name__)

CHECK_INTERVAL = 3600
MARKER = ".last_digest"
NAMES_SHOWN = 3


async def _spent_since(session: AsyncSession, since: datetime) -> dict[str, Decimal]:
    """What left the cards since `since`, one total per currency."""
    rows = await session.execute(
        select(Voucher.currency, Event.payload)
        .join(Event, Event.voucher_id == Voucher.id)
        .where(Event.kind == EventKind.balance_updated, Event.created_at >= since)
    )
    spent: dict[str, Decimal] = defaultdict(Decimal)
    for currency, payload in rows.all():
        spent[currency or FALLBACK_CURRENCY] += Decimal(str(payload.get("spent", "0") or "0"))
    return spent


def _money(blocks: list[CurrencyStats], pick: Callable[[CurrencyStats], Decimal]) -> str:
    """One amount per currency, for a sentence that used to name exactly one.

    Nothing is added up across currencies — that sum is what this replaced. With a
    single currency, which is the normal case, the text is unchanged.

    Everything zero means there is no money to name at all; the sentence still has
    to read, so it gets a zero in the family's main currency.
    """
    parts = [
        f"{format_amount(pick(block))} {block.currency}" for block in blocks if pick(block) > 0
    ]
    return " · ".join(parts) or f"{format_amount(Decimal(0))} {blocks[0].currency}"


async def _expiring_names(session: AsyncSession, within_days: int) -> list[str]:
    today = utcnow().date()
    rows = await session.execute(
        select(Voucher)
        .where(
            Voucher.status == VoucherStatus.active,
            Voucher.valid_until.is_not(None),
            Voucher.valid_until <= today + timedelta(days=within_days),
            Voucher.valid_until >= today,
        )
        .order_by(Voucher.valid_until)
    )
    return [v.merchant or v.title or f"#{v.id}" for v in rows.unique().scalars()]


async def build_digest(session: AsyncSession) -> str | None:
    """The weekly message, or None when there is nothing worth sending."""
    stats = await collect_stats(session)
    blocks = stats.currencies
    cards_active = sum(block.cards_active for block in blocks)
    expired = sum((block.expired_balance for block in blocks), Decimal(0))
    if cards_active == 0 and expired == 0:
        return None

    now = utcnow()
    week = await _spent_since(session, now - timedelta(days=7))
    week_before = await _spent_since(session, now - timedelta(days=14))
    cards_uncertain = sum(block.cards_uncertain for block in blocks)

    lines = [group_t("digest.title"), ""]
    lines.append(
        group_t(
            "digest.on_cards_one" if cards_active == 1 else "digest.on_cards",
            amount=_money(blocks, lambda block: block.on_cards),
            cards=cards_active,
        )
    )

    spent_this_week = {
        currency: amount for currency, amount in week.items() if amount > 0
    }
    if spent_this_week:
        amount = " · ".join(
            f"{format_amount(spent_this_week[currency])} {currency}"
            for currency in sorted(spent_this_week)
        )
        # The comparison with the week before needs one number on each side, so it
        # is offered only when a single currency was spent in both weeks. Two
        # currencies moving in opposite directions is not a sentence.
        currencies = set(spent_this_week) | {c for c, a in week_before.items() if a > 0}
        one = next(iter(currencies)) if len(currencies) == 1 else None
        previous = week_before.get(one, Decimal(0)) - week[one] if one else Decimal(0)
        change = week[one] - previous if one else Decimal(0)
        if one and previous > 0 and abs(change) >= Decimal("0.01"):
            lines.append(
                group_t(
                    "digest.spent_delta",
                    amount=amount,
                    diff=format_amount(abs(change)),
                    direction=group_t("digest.more" if change > 0 else "digest.less"),
                )
            )
        else:
            lines.append(group_t("digest.spent", amount=amount))
    else:
        lines.append(group_t("digest.spent_nothing"))

    if any(block.expiring_soon > 0 for block in blocks):
        names = await _expiring_names(session, stats.expiring_soon_days)
        shown = ", ".join(names[:NAMES_SHOWN])
        if len(names) > NAMES_SHOWN:
            shown += group_t("digest.and_more", count=len(names) - NAMES_SHOWN)
        lines += [
            "",
            group_t(
                "digest.expiring",
                days=stats.expiring_soon_days,
                amount=_money(blocks, lambda block: block.expiring_soon),
                names=shown,
            ),
        ]

    if cards_uncertain > 0:
        lines.append(
            group_t(
                "digest.uncertain_one" if cards_uncertain == 1 else "digest.uncertain",
                amount=_money(blocks, lambda block: block.uncertain_balance),
                cards=cards_uncertain,
            )
        )

    if expired > 0:
        lines.append(
            group_t(
                "digest.expired",
                amount=_money(blocks, lambda block: block.expired_balance),
            )
        )

    return "\n".join(lines)


def _marker_path():
    return settings.data_dir / MARKER


def _current_week() -> str:
    year, week, _ = utcnow().isocalendar()
    return f"{year}-{week:02d}"


def _already_sent_this_week() -> bool:
    marker = _marker_path()
    return marker.exists() and marker.read_text().strip() == _current_week()


async def send_digest(bot: Bot, session: AsyncSession) -> str | None:
    if settings.family_chat_id is None:
        raise RuntimeError(group_t("error.no_chat_for_digest"))
    text = await build_digest(session)
    if text is None:
        return None
    from app.bot import open_app_keyboard

    await bot.send_message(
        settings.family_chat_id, text, reply_markup=open_app_keyboard(group_t("bot.open_cards"))
    )
    return text


async def digest_loop(bot: Bot) -> None:
    """Once a week, on the configured weekday. The marker survives restarts."""
    if settings.family_chat_id is None:
        log.warning("weekly digest disabled: FAMILY_CHAT_ID is not set")
        return

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            now = datetime.now(UTC)
            if now.weekday() != settings.digest_weekday or now.hour != settings.digest_hour_utc:
                continue
            if _already_sent_this_week():
                continue
            async with SessionLocal() as session:
                sent = await send_digest(bot, session)
            _marker_path().write_text(_current_week())
            log.info("weekly digest %s", "sent" if sent else "skipped (nothing to say)")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed digest must not kill the loop
            log.warning("weekly digest failed", exc_info=True)

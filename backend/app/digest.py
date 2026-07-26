"""Weekly summary into the family chat.

The failure mode of this app is silence: cards sit unopened until they expire. So
once a week the bot says how much is lying around and what is about to burn — the
expiring money first, because that is the part you can still act on.

Nothing is sent when there is nothing to act on; a weekly "you have no cards" is
just noise that trains people to ignore the bot.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.i18n import group_t
from app.models import Event, EventKind, Voucher, VoucherStatus, utcnow
from app.services import format_amount
from app.stats import collect_stats

log = logging.getLogger(__name__)

CHECK_INTERVAL = 3600
MARKER = ".last_digest"
NAMES_SHOWN = 3


async def _spent_since(session: AsyncSession, since: datetime) -> Decimal:
    rows = await session.execute(
        select(Event.payload).where(
            Event.kind == EventKind.balance_updated, Event.created_at >= since
        )
    )
    return sum(
        (Decimal(str(payload.get("spent", "0") or "0")) for payload in rows.scalars()),
        Decimal(0),
    )


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
    if stats.cards_active == 0 and stats.expired_balance == 0:
        return None

    now = utcnow()
    week = await _spent_since(session, now - timedelta(days=7))
    week_before = await _spent_since(session, now - timedelta(days=14))
    currency = stats.currency

    lines = [group_t("digest.title"), ""]
    lines.append(
        group_t(
            "digest.on_cards_one" if stats.cards_active == 1 else "digest.on_cards",
            amount=format_amount(stats.on_cards),
            currency=currency,
            cards=stats.cards_active,
        )
    )

    if week > 0:
        change = week - (week_before - week)
        if week_before - week > 0 and abs(change) >= Decimal("0.01"):
            lines.append(
                group_t(
                    "digest.spent_delta",
                    amount=format_amount(week),
                    currency=currency,
                    diff=format_amount(abs(change)),
                    direction=group_t("digest.more" if change > 0 else "digest.less"),
                )
            )
        else:
            lines.append(
                group_t("digest.spent", amount=format_amount(week), currency=currency)
            )
    else:
        lines.append(group_t("digest.spent_nothing"))

    if stats.expiring_soon > 0:
        names = await _expiring_names(session, stats.expiring_soon_days)
        shown = ", ".join(names[:NAMES_SHOWN])
        if len(names) > NAMES_SHOWN:
            shown += group_t("digest.and_more", count=len(names) - NAMES_SHOWN)
        lines += [
            "",
            group_t(
                "digest.expiring",
                days=stats.expiring_soon_days,
                amount=format_amount(stats.expiring_soon),
                currency=currency,
                names=shown,
            ),
        ]

    if stats.uncertain_balance > 0:
        lines.append(
            group_t(
                "digest.uncertain_one" if stats.cards_uncertain == 1 else "digest.uncertain",
                amount=format_amount(stats.uncertain_balance),
                currency=currency,
                cards=stats.cards_uncertain,
            )
        )

    if stats.expired_balance > 0:
        lines.append(
            group_t(
                "digest.expired",
                amount=format_amount(stats.expired_balance),
                currency=currency,
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

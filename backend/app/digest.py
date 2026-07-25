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

    lines = ["🐷 <b>Сводка за неделю</b>", ""]
    lines.append(
        f"На картах: <b>{format_amount(stats.on_cards)} {currency}</b> "
        f"на {stats.cards_active} шт."
    )

    if week > 0:
        change = week - (week_before - week)
        if week_before - week > 0 and abs(change) >= Decimal("0.01"):
            direction = "больше" if change > 0 else "меньше"
            lines.append(
                f"Потратили: {format_amount(week)} {currency} — "
                f"на {format_amount(abs(change))} {direction}, чем неделей раньше"
            )
        else:
            lines.append(f"Потратили: {format_amount(week)} {currency}")
    else:
        lines.append("За неделю ничего не потратили")

    if stats.expiring_soon > 0:
        names = await _expiring_names(session, stats.expiring_soon_days)
        shown = ", ".join(names[:NAMES_SHOWN])
        more = f" и ещё {len(names) - NAMES_SHOWN}" if len(names) > NAMES_SHOWN else ""
        lines += [
            "",
            f"⏳ Истекает за {stats.expiring_soon_days} дней: "
            f"<b>{format_amount(stats.expiring_soon)} {currency}</b> — {shown}{more}",
        ]

    if stats.uncertain_balance > 0:
        lines.append(
            f"❔ Под вопросом: {format_amount(stats.uncertain_balance)} {currency} "
            f"на {stats.cards_uncertain} карт(ах) — проверьте остаток"
        )

    if stats.expired_balance > 0:
        lines.append(
            f"⚠️ Уже истекли, а деньги остались: "
            f"<b>{format_amount(stats.expired_balance)} {currency}</b>"
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
        raise RuntimeError("FAMILY_CHAT_ID не задан — сводку отправлять некуда")
    text = await build_digest(session)
    if text is None:
        return None
    from app.bot import open_app_keyboard

    await bot.send_message(
        settings.family_chat_id, text, reply_markup=open_app_keyboard("Открыть карты")
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

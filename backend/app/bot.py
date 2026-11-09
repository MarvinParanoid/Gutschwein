"""Telegram bot: entry point into the Mini App and the photo -> draft shortcut.

Sending a screenshot to the bot creates a draft voucher with the image already
attached; the fields are then filled in inside the Mini App.
"""

import asyncio
import logging
from datetime import date, timedelta
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from fastapi import HTTPException
from sqlalchemy import or_, select, update

from app import storage
from app.auth import TelegramUser, upsert_user
from app.backup import BackupBusy, send_backup
from app.config import settings
from app.db import SessionLocal
from app.digest import build_digest, digest_loop
from app.i18n import Message as I18nMessage
from app.i18n import default_language, group_t, html_t, language_for
from app.models import EventKind, Voucher, VoucherStatus, utcnow
from app.notify import notify
from app.quickadd import QuickAdd, apply_quick_add, find_pending_draft, parse_quick_add
from app.services import attach_barcode, format_amount, record_event, voucher_label
from app.sessions import LOGIN_TOKEN_TTL, issue_login_token

log = logging.getLogger(__name__)

REMINDER_DAYS = 3
REMINDER_INTERVAL = 6 * 3600


def open_app_keyboard(text: str, chat_type: str) -> InlineKeyboardMarkup | None:
    """The button that opens the Mini App, where Telegram allows one.

    A `web_app` button is private-chat only: in a group Telegram rejects the whole
    message with BUTTON_TYPE_INVALID, not just the button. So a group gets the text
    alone — which is why the family-chat senders (digest, reminders) pass no keyboard.
    """
    if chat_type != "private" or not settings.webapp_url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url))]
        ]
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    def allowed(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.allowed_ids)

    def lang(message: Message) -> str:
        """Whatever language their Telegram is in — same signal the Mini App uses."""
        code = message.from_user.language_code if message.from_user else None
        return language_for(code, default_language())

    @dp.message(Command("id"))
    async def cmd_id(message: Message) -> None:
        """Reports both ids needed to configure the app: the member and the chat."""
        language = lang(message)
        lines = [html_t("bot.your_id", language, user_id=message.from_user.id)]
        if message.chat.type in ("group", "supergroup"):
            lines.append(html_t("bot.chat_id", language, chat_id=message.chat.id))
        await message.answer("\n".join(lines))

    @dp.message(Command("backup"))
    async def cmd_backup(message: Message, bot: Bot) -> None:
        """On-demand backup, so nobody has to wait until the nightly one."""
        if not allowed(message):
            return
        language = lang(message)
        if settings.family_chat_id is None:
            await message.answer(html_t("bot.backup_no_chat", language))
            return
        await message.answer(html_t("bot.backup_working", language))
        try:
            reason = group_t("backup.reason_manual", name=message.from_user.first_name)
            summary = await send_backup(bot, reason)
            await message.answer(html_t("bot.backup_done", language, summary=summary))
        except BackupBusy:
            await message.answer(html_t("bot.backup_busy", language))
        except Exception as exc:  # noqa: BLE001 - report the reason to the user
            log.warning("manual backup failed", exc_info=True)
            await message.answer(html_t("bot.backup_failed", language, error=exc))

    @dp.message(Command("login"))
    async def cmd_login(message: Message) -> None:
        """A one-time link that turns a browser into a logged-in device."""
        if not allowed(message):
            return
        language = lang(message)
        if message.chat.type != "private":
            await message.answer(html_t("bot.login_only_private", language))
            return
        if not settings.webapp_url.startswith("https://"):
            await message.answer(html_t("bot.login_no_url", language))
            return

        async with SessionLocal() as session:
            user = await upsert_user(session, _telegram_user(message))
            token = await issue_login_token(session, user)

        minutes = int(LOGIN_TOKEN_TTL.total_seconds() // 60)
        await message.answer(
            html_t(
                "bot.login_link",
                language,
                minutes=minutes,
                url=f"{settings.webapp_url}/login#{token}",
            ),
            disable_web_page_preview=True,
        )

    @dp.message(Command("digest"))
    async def cmd_digest(message: Message, bot: Bot) -> None:
        """The weekly summary on demand — also the way to see what it looks like."""
        if not allowed(message):
            return
        async with SessionLocal() as session:
            text = await build_digest(session)
        if text is None:
            await message.answer(html_t("bot.digest_nothing", lang(message)))
            return
        await message.answer(
            text,
            reply_markup=open_app_keyboard(
                html_t("bot.open_cards", lang(message)), message.chat.type
            ),
        )

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        language = lang(message)
        if not allowed(message):
            await message.answer(html_t("bot.no_access", language, user_id=message.from_user.id))
            return
        keyboard = open_app_keyboard(html_t("bot.open_app", language), message.chat.type)
        hint = html_t("bot.start", language)
        if not settings.webapp_url.startswith("https://"):
            await message.answer(hint + html_t("bot.no_webapp_url", language))
        else:
            await message.answer(hint, reply_markup=keyboard)

    @dp.message(F.photo | F.document.mime_type.startswith("image/"))
    async def on_image(message: Message, bot: Bot) -> None:
        if not allowed(message):
            return
        picture = message.photo[-1] if message.photo else message.document
        language = lang(message)
        # The upload limit, applied before downloading: Telegram hands bots files of
        # up to 20 MB, and a document claims "image/*" on the sender's word.
        if (picture.file_size or 0) > storage.MAX_IMAGE_BYTES:
            limit = storage.MAX_IMAGE_BYTES // 1024 // 1024
            await message.answer(html_t("error.file_too_big", language, limit=limit))
            return
        buffer = await bot.download(picture.file_id)
        try:
            image_path = await storage.store(buffer.read())
        except HTTPException as exc:
            # Unreadable, a format the app does not take, or too large to decode: say
            # which, instead of leaving the sender without an answer.
            detail = exc.detail
            text = detail.render(language) if isinstance(detail, I18nMessage) else str(detail)
            await message.answer(escape(text))
            return

        async with SessionLocal() as session:
            user = await upsert_user(session, _telegram_user(message))
            voucher = Voucher(
                status=VoucherStatus.draft,
                image_path=image_path,
                created_by_id=user.id,
            )
            await attach_barcode(voucher)
            session.add(voucher)
            await session.flush()
            record_event(session, voucher, user, EventKind.created, {"source": "bot"})
            await session.commit()

            # A caption like "Rewe 50" is all a gift card needs — no app required.
            parsed = parse_quick_add(message.caption or "")
            complete = await apply_quick_add(session, user, voucher, parsed)
            reply = _describe(voucher, complete, parsed, language) + _barcode_note(
                voucher, language
            )
            label = voucher_label(voucher)
            actor = user.display_name

        await message.answer(
            reply, reply_markup=_card_keyboard(complete, language, message.chat.type)
        )
        if complete:
            await _notify_family(message, group_t("notify.card_added", actor=actor, label=label))

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        """Completes the draft the last photo created, or adds a card without a photo."""
        if not allowed(message):
            return
        language = lang(message)
        parsed = parse_quick_add(message.text or "")
        if parsed.is_empty:
            await message.answer(
                html_t("bot.not_understood", language),
                reply_markup=open_app_keyboard(html_t("bot.open_app", language), message.chat.type),
            )
            return

        async with SessionLocal() as session:
            user = await upsert_user(session, _telegram_user(message))
            voucher = await find_pending_draft(session, user)
            if voucher is None:
                if parsed.merchant is None or parsed.amount is None:
                    await message.answer(html_t("bot.no_drafts", language))
                    return
                # No photo, but a complete card is still better than nothing.
                voucher = Voucher(created_by_id=user.id, status=VoucherStatus.draft)
                session.add(voucher)
                await session.flush()
                record_event(session, voucher, user, EventKind.created, {"source": "bot"})
                await session.commit()

            complete = await apply_quick_add(session, user, voucher, parsed)
            reply = _describe(voucher, complete, parsed, language)
            label = voucher_label(voucher)
            actor = user.display_name

        await message.answer(
            reply, reply_markup=_card_keyboard(complete, language, message.chat.type)
        )
        if complete:
            await _notify_family(message, group_t("notify.card_added", actor=actor, label=label))

    return dp


def _telegram_user(message: Message) -> TelegramUser:
    return TelegramUser(
        {
            "id": message.from_user.id,
            "first_name": message.from_user.first_name or "",
            "last_name": message.from_user.last_name or "",
            "username": message.from_user.username or "",
            # Stored on the user so the digest and reminders can address them
            # in the same language even when they are not the ones asking.
            "language_code": message.from_user.language_code or "",
        }
    )


def _card_keyboard(complete: bool, language: str, chat_type: str) -> InlineKeyboardMarkup | None:
    key = "bot.open_card" if complete else "bot.fill_in_app"
    return open_app_keyboard(html_t(key, language), chat_type)


def _describe(voucher: Voucher, complete: bool, parsed: QuickAdd, language: str) -> str:
    """What the bot understood — so a misparse is obvious immediately."""
    if complete:
        return html_t(
            "bot.added",
            language,
            merchant=voucher.merchant,
            amount=format_amount(voucher.balance_amount),
            currency=voucher.currency,
        )
    if voucher.merchant and voucher.value_amount is None:
        return html_t("bot.shop_noted", language, merchant=voucher.merchant)
    if parsed.amount is not None and not voucher.merchant:
        return html_t("bot.amount_noted", language, amount=format_amount(parsed.amount))
    return html_t("bot.draft_created", language)


def _barcode_note(voucher: Voucher, language: str) -> str:
    """Say it now, at the kitchen table, rather than let it surprise you at the till."""
    if voucher.barcode_format:
        return html_t("bot.barcode_found", language, format=voucher.barcode_format)
    return html_t("bot.barcode_missing", language)


async def _notify_family(message: Message, text: str) -> None:
    """Tell the others — unless this very chat is the family chat."""
    if settings.family_chat_id is None or message.chat.id == settings.family_chat_id:
        return
    await notify(text)


def _expiry_message(voucher: Voucher, today: date) -> str:
    left = (voucher.valid_until - today).days
    if left == 0:
        when = group_t("notify.expires_today")
    else:
        plural = "day" if left == 1 else "days"
        when = group_t(f"notify.expires_in_{plural}", days=left)
    # Say when the date is ours, not the card's — otherwise a guess reads as a
    # deadline and people throw away a working card.
    caveat = group_t("notify.expiry_estimated") if voucher.expiry_estimated else ""
    return group_t("notify.expiring", label=voucher_label(voucher), when=when, caveat=caveat)


def _due(today: date) -> tuple:
    """Conditions for a card that should be warned about on `today`.

    `reminded_on` is the expiry date a reminder was sent *for*, not the day it was
    sent. Selecting only cards with no reminder at all (as before) warned once per
    card, ever: a corrected or extended date never got a warning of its own. Now a
    card is due whenever the date it carries is not the one already announced —
    so a moved date, either way, gets one reminder, and the same date never two.

    The window is in UTC dates, like `Voucher.is_expired`: a card due "today" here
    is not yet expired there, and the day turns at the same moment for both.
    """
    return (
        Voucher.status == VoucherStatus.active,
        Voucher.valid_until.is_not(None),
        Voucher.valid_until >= today,
        Voucher.valid_until <= today + timedelta(days=REMINDER_DAYS),
        or_(Voucher.reminded_on.is_(None), Voucher.reminded_on != Voucher.valid_until),
    )


# One pass at a time. The loop is the only caller in production, but a pass that
# overlapped another would read the same unreminded cards and send each twice.
_reminding = asyncio.Lock()


async def remind_expiring(bot: Bot, today: date | None = None) -> int:
    """Warn the family chat about every card due today. Returns how many were sent.

    Per card: read it, send, then record — never record first. A failed send leaves
    the card due, so the next pass tries again; marking the whole batch up front used
    to lose every warning after the first failure.

    No database session is held across the Telegram call. The record is a
    conditional update on the date that was announced: if the date was edited while
    the message was on its way, the new date stays due rather than being marked as
    already announced.
    """
    async with _reminding:
        today = today or utcnow().date()
        async with SessionLocal() as session:
            ids = (await session.execute(select(Voucher.id).where(*_due(today)))).scalars().all()

        sent = 0
        for voucher_id in ids:
            async with SessionLocal() as session:
                # Again, one by one: deleted, used or edited since the list was read.
                voucher = (
                    (
                        await session.execute(
                            select(Voucher).where(Voucher.id == voucher_id, *_due(today))
                        )
                    )
                    .unique()
                    .scalar_one_or_none()
                )
                if voucher is None:
                    continue
                announced = voucher.valid_until
                text = _expiry_message(voucher, today)
            try:
                # No app button: the family chat is a group, and a group rejects one.
                await bot.send_message(settings.family_chat_id, text)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one card must not cost the others
                log.warning(
                    "could not warn about voucher %s; will retry next pass",
                    voucher_id,
                    exc_info=True,
                )
                continue
            async with SessionLocal() as session:
                await session.execute(
                    update(Voucher)
                    .where(Voucher.id == voucher_id, Voucher.valid_until == announced)
                    .values(reminded_on=announced)
                )
                await session.commit()
            sent += 1
        return sent


async def expiry_reminder_loop(bot: Bot) -> None:
    """Warn the family chat about vouchers expiring within REMINDER_DAYS."""
    if settings.family_chat_id is None:
        return
    while True:
        try:
            await remind_expiring(bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive any single failure
            log.warning("expiry reminder loop iteration failed", exc_info=True)
        await asyncio.sleep(REMINDER_INTERVAL)


def create_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run_bot(bot: Bot) -> None:
    """Polling only. The background loops are started by main's lifespan on their
    own: as tasks of this one they ended with it, so a bot that stopped polling (a
    revoked token, a crash) silently took the backups and reminders with it (T10)."""
    dp = build_dispatcher()
    await dp.start_polling(bot, handle_signals=False)


def background_loops(bot: Bot) -> list:
    """What runs beside the bot and needs it to send: reminders and the digest."""
    return [expiry_reminder_loop(bot), digest_loop(bot)]

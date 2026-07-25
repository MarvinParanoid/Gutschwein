"""Telegram bot: entry point into the Mini App and the photo -> draft shortcut.

Sending a screenshot to the bot creates a draft voucher with the image already
attached; the fields are then filled in inside the Mini App.
"""

import asyncio
import logging
from datetime import timedelta

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
from sqlalchemy import select

from app import storage
from app.auth import TelegramUser, upsert_user
from app.config import settings
from app.db import SessionLocal
from app.models import EventKind, Voucher, VoucherStatus, utcnow
from app.services import record_event, voucher_label

log = logging.getLogger(__name__)

REMINDER_DAYS = 3
REMINDER_INTERVAL = 6 * 3600


def open_app_keyboard(text: str = "🐷 Открыть Sparschwein") -> InlineKeyboardMarkup | None:
    if not settings.webapp_url.startswith("https://"):
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

    @dp.message(Command("id"))
    async def cmd_id(message: Message) -> None:
        """Reports both ids needed to configure the app: the member and the chat."""
        lines = [f"Ваш Telegram ID: <code>{message.from_user.id}</code> → ALLOWED_TELEGRAM_IDS"]
        if message.chat.type in ("group", "supergroup"):
            lines.append(f"ID этого чата: <code>{message.chat.id}</code> → FAMILY_CHAT_ID")
        await message.answer("\n".join(lines))

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not allowed(message):
            await message.answer(
                "Это семейное приложение для купонов. Доступа пока нет.\n"
                f"Ваш Telegram ID: <code>{message.from_user.id}</code>"
            )
            return
        keyboard = open_app_keyboard()
        hint = (
            "Пришлите скрин или фото купона — я создам черновик, "
            "останется заполнить поля в приложении."
        )
        if keyboard is None:
            await message.answer(
                f"{hint}\n\n⚠️ WEBAPP_URL не настроен, кнопка приложения недоступна."
            )
        else:
            await message.answer(f"Привет! {hint}", reply_markup=keyboard)

    @dp.message(F.photo | F.document.mime_type.startswith("image/"))
    async def on_image(message: Message, bot: Bot) -> None:
        if not allowed(message):
            return
        file_id = (
            message.photo[-1].file_id if message.photo else message.document.file_id
        )
        buffer = await bot.download(file_id)
        image_path = storage.save_bytes(buffer.read())

        async with SessionLocal() as session:
            user = await upsert_user(
                session,
                TelegramUser(
                    {
                        "id": message.from_user.id,
                        "first_name": message.from_user.first_name or "",
                        "last_name": message.from_user.last_name or "",
                        "username": message.from_user.username or "",
                    }
                ),
            )
            voucher = Voucher(
                status=VoucherStatus.draft,
                title=(message.caption or "").strip()[:256],
                image_path=image_path,
                created_by_id=user.id,
            )
            session.add(voucher)
            await session.flush()
            record_event(session, voucher, user, EventKind.created, {"source": "bot"})
            await session.commit()

        await message.answer(
            "📸 Черновик создан. Заполните поля в приложении — он ждёт во вкладке «Черновики».",
            reply_markup=open_app_keyboard("Заполнить купон"),
        )

    @dp.message()
    async def fallback(message: Message) -> None:
        if not allowed(message):
            return
        await message.answer(
            "Пришлите фото купона или откройте приложение.",
            reply_markup=open_app_keyboard(),
        )

    return dp


async def expiry_reminder_loop(bot: Bot) -> None:
    """Warn the family chat once about vouchers expiring within REMINDER_DAYS."""
    if settings.family_chat_id is None:
        return
    while True:
        try:
            today = utcnow().date()
            deadline = today + timedelta(days=REMINDER_DAYS)
            async with SessionLocal() as session:
                rows = await session.execute(
                    select(Voucher).where(
                        Voucher.status == VoucherStatus.active,
                        Voucher.valid_until.is_not(None),
                        Voucher.valid_until <= deadline,
                        Voucher.valid_until >= today,
                        Voucher.reminded_on.is_(None),
                    )
                )
                expiring = list(rows.unique().scalars().all())
                for voucher in expiring:
                    voucher.reminded_on = today
                if expiring:
                    await session.commit()

            for voucher in expiring:
                left = (voucher.valid_until - today).days
                when = "истекает сегодня" if left == 0 else f"истекает через {left} дн."
                await bot.send_message(
                    settings.family_chat_id,
                    f"⏳ <b>{voucher_label(voucher)}</b> {when}",
                    reply_markup=open_app_keyboard("Посмотреть"),
                )
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
    dp = build_dispatcher()
    reminders = asyncio.create_task(expiry_reminder_loop(bot))
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        reminders.cancel()

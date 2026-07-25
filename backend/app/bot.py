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
from app.backup import backup_loop, send_backup
from app.config import settings
from app.db import SessionLocal
from app.digest import build_digest, digest_loop
from app.models import EventKind, Voucher, VoucherStatus, utcnow
from app.notify import notify
from app.quickadd import QuickAdd, apply_quick_add, find_pending_draft, parse_quick_add
from app.services import attach_barcode, format_amount, record_event, voucher_label
from app.sessions import LOGIN_TOKEN_TTL, issue_login_token

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

    @dp.message(Command("backup"))
    async def cmd_backup(message: Message, bot: Bot) -> None:
        """On-demand backup, so nobody has to wait until the nightly one."""
        if not allowed(message):
            return
        if settings.family_chat_id is None:
            await message.answer("FAMILY_CHAT_ID не настроен — бэкап отправлять некуда.")
            return
        await message.answer("Собираю бэкап…")
        try:
            summary = await send_backup(bot, f"по запросу от {message.from_user.first_name}")
            await message.answer(f"Готово: {summary}")
        except Exception as exc:  # noqa: BLE001 - report the reason to the user
            log.warning("manual backup failed", exc_info=True)
            await message.answer(f"Не получилось: {exc}")

    @dp.message(Command("login"))
    async def cmd_login(message: Message) -> None:
        """A one-time link that turns a browser into a logged-in device."""
        if not allowed(message):
            return
        if message.chat.type != "private":
            await message.answer("Ссылку для входа пришлю только в личку — напишите мне туда.")
            return
        if not settings.webapp_url.startswith("https://"):
            await message.answer("WEBAPP_URL не настроен — ссылку сформировать не из чего.")
            return

        async with SessionLocal() as session:
            user = await upsert_user(session, _telegram_user(message))
            token = await issue_login_token(session, user)

        minutes = int(LOGIN_TOKEN_TTL.total_seconds() // 60)
        await message.answer(
            f"Ссылка для входа в браузере (действует {minutes} минут, один раз):\n"
            f"{settings.webapp_url}/login#{token}\n\n"
            "Откройте её в браузере телефона и добавьте приложение на домашний экран. "
            "Никому не пересылайте — она пускает в наши карты.",
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
            await message.answer("Пока не о чем рассказывать: активных карт нет.")
            return
        await message.answer(text, reply_markup=open_app_keyboard("Открыть карты"))

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
            "Купили карту — пришлите скрин <b>с подписью</b> «Rewe 50», "
            "и она сразу появится в списке.\n\n"
            "Без подписи получится черновик: тогда просто напишите следом "
            "«Rewe 50» — или отдельно «Rewe», а потом «50».\n\n"
            "Ещё умею /login (вход в браузере), /digest, /backup и /id."
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
            reply = _describe(voucher, complete, parsed) + _barcode_note(voucher)
            label = voucher_label(voucher)
            actor = user.display_name

        await message.answer(reply, reply_markup=open_app_keyboard(
            "Открыть карту" if complete else "Заполнить в приложении"
        ))
        if complete:
            await _notify_family(message, f"🐷 {actor} добавил карту: <b>{label}</b>")

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        """Completes the draft the last photo created, or adds a card without a photo."""
        if not allowed(message):
            return
        parsed = parse_quick_add(message.text or "")
        if parsed.is_empty:
            await message.answer(
                "Не понял. Пришлите скрин карты с подписью «Rewe 50» — "
                "или напишите так же текстом.",
                reply_markup=open_app_keyboard(),
            )
            return

        async with SessionLocal() as session:
            user = await upsert_user(session, _telegram_user(message))
            voucher = await find_pending_draft(session, user)
            if voucher is None:
                if parsed.merchant is None or parsed.amount is None:
                    await message.answer(
                        "Черновиков нет. Пришлите скрин карты — можно сразу с подписью "
                        "«Rewe 50»."
                    )
                    return
                # No photo, but a complete card is still better than nothing.
                voucher = Voucher(created_by_id=user.id, status=VoucherStatus.draft)
                session.add(voucher)
                await session.flush()
                record_event(session, voucher, user, EventKind.created, {"source": "bot"})
                await session.commit()

            complete = await apply_quick_add(session, user, voucher, parsed)
            reply = _describe(voucher, complete, parsed)
            label = voucher_label(voucher)
            actor = user.display_name

        await message.answer(reply, reply_markup=open_app_keyboard(
            "Открыть карту" if complete else "Заполнить в приложении"
        ))
        if complete:
            await _notify_family(message, f"🐷 {actor} добавил карту: <b>{label}</b>")

    return dp


def _telegram_user(message: Message) -> TelegramUser:
    return TelegramUser(
        {
            "id": message.from_user.id,
            "first_name": message.from_user.first_name or "",
            "last_name": message.from_user.last_name or "",
            "username": message.from_user.username or "",
        }
    )


def _describe(voucher: Voucher, complete: bool, parsed: QuickAdd) -> str:
    """What the bot understood — so a misparse is obvious immediately."""
    if complete:
        return (
            f"✅ Добавил: <b>{voucher.merchant}</b> · "
            f"{format_amount(voucher.balance_amount)} {voucher.currency}"
        )
    if voucher.merchant and voucher.value_amount is None:
        return f"Записал магазин: <b>{voucher.merchant}</b>. Теперь сумму — просто числом."
    if parsed.amount is not None and not voucher.merchant:
        return f"Записал сумму {format_amount(parsed.amount)}. Теперь название магазина."
    return "📸 Черновик создан. Напишите магазин и сумму — например «Rewe 50»."


def _barcode_note(voucher: Voucher) -> str:
    """Say it now, at the kitchen table, rather than let it surprise you at the till."""
    if voucher.barcode_format:
        return f"\n▮▮ Штрихкод распознан ({voucher.barcode_format}) — покажу его чётким."
    return (
        "\n⚠️ Штрихкод в скрине не читается — покажу саму картинку. "
        "Пришлите скрин целиком, не обрезанный: в мелком коде штрихи теряются."
    )


async def _notify_family(message: Message, text: str) -> None:
    """Tell the others — unless this very chat is the family chat."""
    if settings.family_chat_id is None or message.chat.id == settings.family_chat_id:
        return
    await notify(text)


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
                # Say when the date is ours, not the card's — otherwise a guess
                # reads as a deadline and people throw away a working card.
                caveat = " (срок по правилу магазина)" if voucher.expiry_estimated else ""
                await bot.send_message(
                    settings.family_chat_id,
                    f"⏳ <b>{voucher_label(voucher)}</b> {when}{caveat}",
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
    background = [
        asyncio.create_task(expiry_reminder_loop(bot)),
        asyncio.create_task(backup_loop(bot)),
        asyncio.create_task(digest_loop(bot)),
    ]
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        for task in background:
            task.cancel()

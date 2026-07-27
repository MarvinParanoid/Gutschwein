"""The bot's own handlers, driven through the dispatcher.

Everything under them — parsing a caption, applying it to a draft, formatting an
amount — has its own tests. What was never exercised is the layer that turns a
Telegram update into those calls, and that is where both production incidents so
far actually happened: an amount rendered as "1E+1" in a reply, and a crash in
the photo path. Neither could be caught below this line.

The bot talks to Telegram through its session, so a session that records the
calls instead of sending them is enough to see what a handler decided to do.
"""

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message, PhotoSize, Update
from aiogram.types import User as TgUser
from sqlalchemy import select

from app.bot import build_dispatcher
from app.config import settings
from app.db import SessionLocal
from app.models import Voucher, VoucherStatus

MEMBER = 770001
OUTSIDER = 770002
CHAT = 770001
# Shop names of their own: the suite shares one database, and "Rewe" is created
# by half the other files.
SHOP_PHOTO = "Botmarkt"
SHOP_TEXT = "Botladen"


class RecordingSession(BaseSession):
    """Answers every Telegram call locally and keeps what was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - the signature is aiogram's, not ours
    ):
        self.calls.append(method)
        return Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=CHAT, type="private"),
        ).as_(bot)

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover - unused
        yield b""

    async def close(self) -> None:
        pass

    @property
    def replies(self) -> list[str]:
        return [m.text for m in self.calls if isinstance(m, SendMessage)]


@pytest.fixture
def bot() -> Bot:
    return Bot(token="42:TEST", session=RecordingSession())


@pytest.fixture
def session(bot: Bot) -> RecordingSession:
    return bot.session  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def member_is_allowed(monkeypatch, client):
    """`client` is here for its side effect: it runs the migrations."""
    monkeypatch.setattr(settings, "allowed_telegram_ids", str(MEMBER))
    monkeypatch.setattr(settings, "webapp_url", "https://example.com")


def _message(
    text: str = "",
    *,
    user_id: int = MEMBER,
    photo: bool = False,
    caption: str = "",
    chat_type: str = "private",
) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=CHAT, type=chat_type),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Аня", language_code="ru"),
        text=text or None,
        caption=caption or None,
        photo=[PhotoSize(file_id="F", file_unique_id="U", width=10, height=10)] if photo else None,
    )


async def _feed(bot: Bot, message: Message) -> None:
    await build_dispatcher().feed_update(bot, Update(update_id=1, message=message))


async def _card_count() -> int:
    """The suite shares one database, so what matters is the change, not the total."""
    async with SessionLocal() as db:
        return len((await db.execute(select(Voucher))).scalars().all())


async def test_a_stranger_is_told_their_id_and_nothing_else(bot, session) -> None:
    before = await _card_count()
    await _feed(bot, _message("/start", user_id=OUTSIDER))

    assert len(session.replies) == 1
    assert str(OUTSIDER) in session.replies[0]
    assert await _card_count() == before


async def test_a_caption_turns_a_photo_into_a_finished_card(bot, session, monkeypatch) -> None:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
        b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(type(bot), "download", lambda self, file_id, **kw: _as_bytes(png))

    await _feed(bot, _message(photo=True, caption=f"{SHOP_PHOTO} 50"))

    async with SessionLocal() as db:
        rows = await db.execute(select(Voucher).where(Voucher.merchant == SHOP_PHOTO))
        cards = rows.scalars().all()
    assert len(cards) == 1
    card = cards[0]
    assert card.status == VoucherStatus.active
    assert str(card.value_amount) == "50.00"
    assert card.image_path  # the picture was stored, not dropped

    # The reply says what was understood, and says it as money, not as 5E+1.
    assert "50 EUR" in session.replies[0]


async def _as_bytes(data: bytes) -> BytesIO:
    return BytesIO(data)


async def test_text_alone_creates_a_card_without_a_photo(bot, session) -> None:
    await _feed(bot, _message(f"{SHOP_TEXT} 30"))

    async with SessionLocal() as db:
        card = (
            await db.execute(select(Voucher).where(Voucher.merchant == SHOP_TEXT))
        ).scalar_one()
    assert str(card.balance_amount) == "30.00"
    assert card.image_path is None
    assert "30 EUR" in session.replies[0]


async def test_nonsense_gets_an_explanation_rather_than_a_card(bot, session) -> None:
    before = await _card_count()
    await _feed(bot, _message("здравствуйте"))

    assert await _card_count() == before
    assert "скрин" in session.replies[0].lower()


async def test_id_reports_the_chat_too_in_a_group(bot, session) -> None:
    await _feed(bot, _message("/id", chat_type="supergroup"))

    assert str(MEMBER) in session.replies[0]
    assert "FAMILY_CHAT_ID" in session.replies[0]


async def test_login_sends_a_link_only_in_private(bot, session) -> None:
    await _feed(bot, _message("/login"))
    assert "https://example.com/login#" in session.replies[0]

    await _feed(bot, _message("/login", chat_type="supergroup"))
    assert "https://example.com/login#" not in session.replies[1]

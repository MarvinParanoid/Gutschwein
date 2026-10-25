"""Warning the family chat about a card that is about to expire.

The whole app exists to make this message arrive, so the test is about what happens
when it does not: one card must never cost the others their warning.
"""

from datetime import timedelta

from fastapi.testclient import TestClient

from app import bot as bot_module
from app.db import SessionLocal
from app.models import User, Voucher, VoucherStatus, utcnow


class FakeBot:
    """Records what was sent, and fails on whichever labels it was told to."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.sent: list[str] = []
        self.fail_on = fail_on or set()

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        # What Telegram does with a Mini App button in a group: the family chat is
        # one, and the whole message is rejected, not just the button.
        if kwargs.get("reply_markup") is not None:
            raise RuntimeError("Bad Request: BUTTON_TYPE_INVALID")
        for bad in self.fail_on:
            if bad in text:
                raise RuntimeError(f"Bad Request: can't parse entities ({bad})")
        self.sent.append(text)


async def _expiring(*merchants: str) -> list[int]:
    """Active cards that all expire tomorrow, none of them warned about yet."""
    async with SessionLocal() as session:
        member = User(first_name="Напоминалка")
        session.add(member)
        await session.flush()
        ids = []
        for merchant in merchants:
            voucher = Voucher(
                merchant=merchant,
                status=VoucherStatus.active,
                valid_until=utcnow().date() + timedelta(days=1),
                created_by_id=member.id,
            )
            session.add(voucher)
            await session.flush()
            ids.append(voucher.id)
        await session.commit()
        return ids


async def _reminded(voucher_id: int) -> bool:
    async with SessionLocal() as session:
        voucher = await session.get(Voucher, voucher_id)
        assert voucher is not None
        return voucher.reminded_on is not None


async def _run_one_pass(bot: FakeBot, monkeypatch) -> None:
    """One iteration of the loop, without the six-hour sleep at the end."""

    async def stop(_seconds: float) -> None:
        raise StopAsyncIteration

    monkeypatch.setattr(bot_module.asyncio, "sleep", stop)
    try:
        await bot_module.expiry_reminder_loop(bot)
    except StopAsyncIteration:
        pass


async def test_every_expiring_card_is_warned_about(client: TestClient, monkeypatch) -> None:
    ids = await _expiring("Первый", "Второй", "Третий")
    monkeypatch.setattr(bot_module.settings, "family_chat_id", 42)

    bot = FakeBot()
    await _run_one_pass(bot, monkeypatch)

    assert len(bot.sent) == 3
    assert all([await _reminded(i) for i in ids])


async def test_a_card_that_could_not_be_sent_is_warned_about_next_time(
    client: TestClient, monkeypatch
) -> None:
    """The bug: the batch was marked reminded up front, then sent one by one.

    A single failed send aborted the rest of the loop, and because `reminded_on` was
    already written, the cards after it were never warned about at all — silently,
    in the one feature the app is for.
    """
    first, broken, last = await _expiring("Целый", "Сломанный", "Последний")
    monkeypatch.setattr(bot_module.settings, "family_chat_id", 42)

    bot = FakeBot(fail_on={"Сломанный"})
    await _run_one_pass(bot, monkeypatch)

    # The other two went out and are recorded; the broken one is untouched.
    assert len(bot.sent) == 2
    assert await _reminded(first) and await _reminded(last)
    assert not await _reminded(broken)

    # …and it is picked up again on the next pass, once sending works.
    healed = FakeBot()
    await _run_one_pass(healed, monkeypatch)
    assert len(healed.sent) == 1
    assert await _reminded(broken)

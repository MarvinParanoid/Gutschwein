"""Warning the family chat about a card that is about to expire.

The whole app exists to make this message arrive, so the test is about what happens
when it does not: one card must never cost the others their warning.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

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


# --- the reminder follows the current date (T7) -------------------------------------------

TODAY = date(2031, 3, 14)


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setattr(bot_module.settings, "family_chat_id", 42)


async def _card(
    valid_until: date | None, status: VoucherStatus = VoucherStatus.active
) -> tuple[int, str]:
    """A card with a name no other test uses, so its messages can be told apart."""
    name = f"T7-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as session:
        member = User(first_name="T7")
        session.add(member)
        await session.flush()
        voucher = Voucher(
            merchant=name, status=status, valid_until=valid_until, created_by_id=member.id
        )
        session.add(voucher)
        await session.commit()
        return voucher.id, name


async def _set(voucher_id: int, **values: object) -> None:
    async with SessionLocal() as session:
        await session.execute(update(Voucher).where(Voucher.id == voucher_id).values(**values))
        await session.commit()


async def _remind(bot: FakeBot, today: date = TODAY) -> None:
    await bot_module.remind_expiring(bot, today)


def _about(bot: FakeBot, name: str) -> list[str]:
    return [text for text in bot.sent if name in text]


async def _reminded_for(voucher_id: int) -> date | None:
    async with SessionLocal() as session:
        return (await session.get(Voucher, voucher_id)).reminded_on


async def test_the_first_reminder_records_the_date_it_announced(client, chat) -> None:
    card, name = await _card(TODAY + timedelta(days=2))
    bot = FakeBot()

    await _remind(bot)

    assert len(_about(bot, name)) == 1
    # The expiry date, not the day it was sent: that is what makes a new date due.
    assert await _reminded_for(card) == TODAY + timedelta(days=2)


async def test_running_again_sends_nothing_new(client, chat) -> None:
    _, name = await _card(TODAY + timedelta(days=1))
    bot = FakeBot()

    await _remind(bot)
    await _remind(bot)
    await _remind(bot, TODAY + timedelta(days=1))  # the next day, still the same date

    assert len(_about(bot, name)) == 1


async def test_a_date_moved_forward_is_announced_again_when_it_comes_near(client, chat) -> None:
    """The bug: once reminded, a card was never reminded again, whatever its date."""
    card, name = await _card(TODAY + timedelta(days=1))
    bot = FakeBot()
    await _remind(bot)

    await _set(card, valid_until=TODAY + timedelta(days=30))
    await _remind(bot)  # far away now: nothing yet
    assert len(_about(bot, name)) == 1

    await _remind(bot, TODAY + timedelta(days=28))
    assert len(_about(bot, name)) == 2
    assert await _reminded_for(card) == TODAY + timedelta(days=30)


async def test_a_date_moved_backward_is_announced_with_the_new_date(client, chat) -> None:
    card, name = await _card(TODAY + timedelta(days=3))
    bot = FakeBot()
    await _remind(bot)

    await _set(card, valid_until=TODAY + timedelta(days=1))
    await _remind(bot)

    assert len(_about(bot, name)) == 2
    assert await _reminded_for(card) == TODAY + timedelta(days=1)


async def test_a_removed_date_is_silent_and_a_restored_one_is_not_announced_twice(
    client, chat
) -> None:
    card, name = await _card(TODAY + timedelta(days=2))
    bot = FakeBot()
    await _remind(bot)

    await _set(card, valid_until=None)
    await _remind(bot)
    assert len(_about(bot, name)) == 1

    # The same date back: it was announced already.
    await _set(card, valid_until=TODAY + timedelta(days=2))
    await _remind(bot)
    assert len(_about(bot, name)) == 1

    # A different date: that one was not.
    await _set(card, valid_until=TODAY + timedelta(days=3))
    await _remind(bot)
    assert len(_about(bot, name)) == 2


async def test_editing_through_the_api_makes_the_card_due_again(client, chat) -> None:
    """The path a person takes: the card form's PATCH, not a direct write."""
    tomorrow = utcnow().date() + timedelta(days=1)
    card = client.post(
        "/api/vouchers",
        json={"merchant": f"T7-api-{uuid.uuid4().hex[:6]}", "valid_until": str(tomorrow)},
    ).json()
    bot = FakeBot()
    await bot_module.remind_expiring(bot)

    corrected = tomorrow + timedelta(days=1)
    edited = client.patch(f"/api/vouchers/{card['id']}", json={"valid_until": str(corrected)})
    assert edited.status_code == 200
    await bot_module.remind_expiring(bot)

    assert len(_about(bot, card["merchant"])) == 2
    assert await _reminded_for(card["id"]) == corrected


async def test_a_failed_send_is_not_recorded_and_is_retried(client, chat) -> None:
    card, name = await _card(TODAY + timedelta(days=1))

    await _remind(FakeBot(fail_on={name}))
    assert await _reminded_for(card) is None

    bot = FakeBot()
    await _remind(bot)
    assert len(_about(bot, name)) == 1
    assert await _reminded_for(card) == TODAY + timedelta(days=1)


async def test_concurrent_passes_send_each_reminder_once(client, chat) -> None:
    cards = [await _card(TODAY + timedelta(days=1)) for _ in range(3)]

    class SlowBot(FakeBot):
        async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
            await asyncio.sleep(0.01)  # both passes are in flight at once
            await super().send_message(chat_id, text, **kwargs)

    bot = SlowBot()
    await asyncio.gather(_remind(bot), _remind(bot), _remind(bot))

    for _, name in cards:
        assert len(_about(bot, name)) == 1


async def test_a_date_edited_during_the_send_stays_due(client, chat) -> None:
    """The record is for the date that was announced, not whatever is there now."""
    card, name = await _card(TODAY + timedelta(days=1))

    class EditingBot(FakeBot):
        async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
            await super().send_message(chat_id, text, **kwargs)
            await _set(card, valid_until=TODAY + timedelta(days=2))

    await _remind(EditingBot())
    assert await _reminded_for(card) is None

    bot = FakeBot()
    await _remind(bot)
    assert len(_about(bot, name)) == 1


@pytest.mark.parametrize(
    ("status", "valid_until"),
    [
        (VoucherStatus.used, TODAY + timedelta(days=1)),
        (VoucherStatus.archived, TODAY + timedelta(days=1)),
        (VoucherStatus.draft, TODAY + timedelta(days=1)),
        (VoucherStatus.active, TODAY - timedelta(days=1)),  # already expired
        (VoucherStatus.active, TODAY + timedelta(days=4)),  # not yet
        (VoucherStatus.active, None),
    ],
)
async def test_cards_that_are_not_due_are_left_alone(client, chat, status, valid_until) -> None:
    _, name = await _card(valid_until, status)
    bot = FakeBot()

    await _remind(bot)

    assert _about(bot, name) == []


async def test_a_deleted_card_is_not_announced(client, chat) -> None:
    card, name = await _card(TODAY + timedelta(days=1))
    async with SessionLocal() as session:
        await session.delete(await session.get(Voucher, card))
        await session.commit()
    bot = FakeBot()

    await _remind(bot)

    assert _about(bot, name) == []


@pytest.mark.parametrize(
    ("now", "announced", "expired"),
    [
        # The last second of the 14th, UTC: a card dated the 14th expires today.
        (datetime(2031, 3, 14, 23, 59, 59, tzinfo=UTC), "сегодня", False),
        # One second later it is the 15th: the same card is expired and silent.
        (datetime(2031, 3, 15, 0, 0, 0, tzinfo=UTC), None, True),
    ],
)
async def test_the_day_turns_at_utc_midnight_for_reminders_and_expiry_alike(
    client, chat, monkeypatch, now, announced, expired
) -> None:
    """One clock for both: a card the reminder calls "today" is not yet expired on
    the card page, and the moment it is expired there the reminder stops."""
    card, name = await _card(date(2031, 3, 14))
    monkeypatch.setattr(bot_module, "utcnow", lambda: now)
    monkeypatch.setattr("app.models.utcnow", lambda: now)
    bot = FakeBot()

    await bot_module.remind_expiring(bot)

    messages = _about(bot, name)
    if announced is None:
        assert messages == []
    else:
        assert len(messages) == 1 and announced in messages[0]
    async with SessionLocal() as session:
        assert (await session.get(Voucher, card)).is_expired is expired

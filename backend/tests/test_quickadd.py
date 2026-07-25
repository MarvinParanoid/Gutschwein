"""Parsing "Rewe 50" — the whole point is that it works on what people actually type."""

from decimal import Decimal

import pytest

from app.quickadd import parse_quick_add


@pytest.mark.parametrize(
    ("text", "merchant", "amount"),
    [
        ("Rewe 50", "Rewe", "50"),
        ("rewe 12,50", "rewe", "12.50"),
        ("Kaufland 40 EUR", "Kaufland", "40"),
        ("Jet Tankstelle 60", "Jet Tankstelle", "60"),
        ("Total Energies 25 евро", "Total Energies", "25"),
        ("Rossmann 20.99", "Rossmann", "20.99"),
        ("  Penny   30  ", "Penny", "30"),
        ("DM 15€", "DM", "15"),
        # Amount first is unusual but unambiguous.
        ("50 Rewe", "Rewe", "50"),
        # Shop only: the amount can follow in the next message.
        ("Rewe", "Rewe", None),
        ("Jet Tankstelle", "Jet Tankstelle", None),
        # Amount only: completes a draft that already knows the shop.
        ("50", None, "50"),
        ("12,50", None, "12.50"),
        # Nothing usable.
        ("", None, None),
        ("   ", None, None),
    ],
)
def test_parsing(text: str, merchant: str | None, amount: str | None) -> None:
    parsed = parse_quick_add(text)
    assert parsed.merchant == merchant
    assert parsed.amount == (Decimal(amount) if amount is not None else None)


def test_last_number_wins_so_digits_in_names_survive() -> None:
    parsed = parse_quick_add("5 Sterne Markt 30")
    assert parsed.merchant == "5 Sterne Markt"
    assert parsed.amount == Decimal("30")


def test_absurd_amounts_are_ignored_but_the_name_is_kept() -> None:
    parsed = parse_quick_add("Rewe 9999999")
    assert parsed.merchant == "Rewe 9999999"
    assert parsed.amount is None

    zero = parse_quick_add("Rewe 0")
    assert zero.merchant == "Rewe"
    assert zero.amount is None


async def _draft(session, user):
    """A draft exactly as the photo handler creates it."""
    from app.models import EventKind, Voucher, VoucherStatus
    from app.services import record_event

    voucher = Voucher(status=VoucherStatus.draft, created_by_id=user.id, image_path=None)
    session.add(voucher)
    await session.flush()
    record_event(session, voucher, user, EventKind.created, {"source": "bot"})
    await session.commit()
    await session.refresh(voucher)
    return voucher


async def _user(session, telegram_id: int):
    from app.auth import TelegramUser, upsert_user

    return await upsert_user(session, TelegramUser({"id": telegram_id, "first_name": "Бот-тест"}))


async def test_caption_in_one_go_activates_the_card() -> None:
    from app.db import SessionLocal
    from app.models import VoucherStatus
    from app.quickadd import apply_quick_add

    async with SessionLocal() as session:
        user = await _user(session, 777001)
        voucher = await _draft(session, user)

        complete = await apply_quick_add(session, user, voucher, parse_quick_add("Rewe 50"))

        assert complete is True
        assert voucher.status == VoucherStatus.active
        assert voucher.merchant == "Rewe"
        assert voucher.value_amount == Decimal("50")
        # The balance is what makes it spendable money, not just a nominal.
        assert voucher.balance_amount == Decimal("50")


async def test_shop_then_amount_in_two_messages() -> None:
    from app.db import SessionLocal
    from app.models import VoucherStatus
    from app.quickadd import apply_quick_add, find_pending_draft

    async with SessionLocal() as session:
        user = await _user(session, 777002)
        voucher = await _draft(session, user)

        # "Rewe" alone must not make it spendable yet.
        assert await apply_quick_add(session, user, voucher, parse_quick_add("Rewe")) is False
        assert voucher.status == VoucherStatus.draft

        found = await find_pending_draft(session, user)
        assert found is not None and found.id == voucher.id

        assert await apply_quick_add(session, user, found, parse_quick_add("50")) is True
        assert found.status == VoucherStatus.active
        assert found.balance_amount == Decimal("50")

        # Nothing is pending any more.
        assert await find_pending_draft(session, user) is None


async def test_history_records_what_the_bot_did() -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Event
    from app.quickadd import apply_quick_add

    async with SessionLocal() as session:
        user = await _user(session, 777003)
        voucher = await _draft(session, user)
        await apply_quick_add(session, user, voucher, parse_quick_add("Penny 30"))

        rows = await session.execute(
            select(Event).where(Event.voucher_id == voucher.id).order_by(Event.id)
        )
        kinds = [e.kind for e in rows.unique().scalars().all()]
        assert kinds == ["created", "updated", "published"]


def test_long_names_are_truncated_to_the_column_width() -> None:
    parsed = parse_quick_add("Ш" * 200 + " 50")
    assert parsed.merchant is not None
    assert len(parsed.merchant) == 128

"""The weekly digest, built on a database of its own so the numbers are exact."""

from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.digest import build_digest
from app.models import (
    Base,
    Event,
    EventKind,
    User,
    ValueKind,
    Voucher,
    VoucherStatus,
    utcnow,
)


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/digest.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


async def make_user(session: AsyncSession) -> User:
    user = User(telegram_id=42, first_name="Аня")
    session.add(user)
    await session.flush()
    return user


async def add_card(
    session: AsyncSession,
    user: User,
    merchant: str,
    balance: str,
    *,
    valid_until=None,
    currency: str = "EUR",
    status: VoucherStatus = VoucherStatus.active,
) -> Voucher:
    card = Voucher(
        merchant=merchant,
        value_kind=ValueKind.amount,
        value_amount=Decimal(balance),
        balance_amount=Decimal(balance),
        currency=currency,
        valid_until=valid_until,
        status=status,
        created_by_id=user.id,
    )
    session.add(card)
    await session.flush()
    return card


async def add_spend(session: AsyncSession, card: Voucher, user: User, amount: str, days_ago: int):
    session.add(
        Event(
            voucher_id=card.id,
            actor_id=user.id,
            kind=EventKind.balance_updated,
            payload={"spent": amount, "remaining": "0", "note": ""},
            created_at=utcnow() - timedelta(days=days_ago),
        )
    )
    await session.flush()


async def test_nothing_to_say_sends_nothing(session: AsyncSession) -> None:
    """A weekly "you have no cards" would only teach people to mute the bot."""
    assert await build_digest(session) is None


async def test_reports_what_is_on_the_cards(session: AsyncSession) -> None:
    user = await make_user(session)
    await add_card(session, user, "Rewe", "50")
    await add_card(session, user, "Penny", "25.50")

    text = await build_digest(session)

    assert "Сводка за неделю" in text
    assert "75.5 EUR" in text
    assert "на 2 шт." in text
    assert "За неделю ничего не потратили" in text


async def test_compares_with_the_week_before(session: AsyncSession) -> None:
    user = await make_user(session)
    card = await add_card(session, user, "Rewe", "100")
    await add_spend(session, card, user, "10", days_ago=2)
    await add_spend(session, card, user, "30", days_ago=10)

    text = await build_digest(session)

    # 10 this week against 30 the week before.
    assert "Потратили: 10 EUR" in text
    assert "на 20 меньше" in text


async def test_expiring_money_is_named(session: AsyncSession) -> None:
    user = await make_user(session)
    soon = utcnow().date() + timedelta(days=5)
    await add_card(session, user, "Kaufland", "40", valid_until=soon)
    await add_card(session, user, "Rossmann", "12", valid_until=soon)

    text = await build_digest(session)

    assert "Истекает за 30 дней" in text
    assert "52 EUR" in text
    assert "Kaufland" in text and "Rossmann" in text


async def test_already_expired_money_is_flagged(session: AsyncSession) -> None:
    user = await make_user(session)
    expired = utcnow().date() - timedelta(days=3)
    await add_card(session, user, "MediaMarkt", "25", valid_until=expired)

    text = await build_digest(session)

    assert "Уже истекли" in text
    assert "25 EUR" in text


@pytest.mark.parametrize("status", [VoucherStatus.used, VoucherStatus.archived])
async def test_spent_and_archived_cards_stay_out_of_the_balance(
    session: AsyncSession, status: VoucherStatus
) -> None:
    user = await make_user(session)
    await add_card(session, user, "Rewe", "50")
    await add_card(session, user, "Ikea", "999", status=status)

    text = await build_digest(session)

    assert "50 EUR" in text
    assert "999" not in text


async def test_every_currency_is_named_on_its_own(session: AsyncSession) -> None:
    """One sentence, two amounts — never one amount made of two currencies."""
    user = await make_user(session)
    euro = await add_card(session, user, "Rewe", "30")
    zloty = await add_card(session, user, "Biedronka", "200", currency="PLN")
    await add_spend(session, euro, user, "10", days_ago=2)
    await add_spend(session, zloty, user, "115.73", days_ago=2)

    text = await build_digest(session)

    assert "30 EUR · 200 PLN" in text
    assert "Потратили: 10 EUR · 115.73 PLN" in text
    # 230 would be the old answer: a złoty added to a euro, labelled with whichever
    # currency the database returned first.
    assert "230" not in text
    # No comparison with the week before: two currencies moving at once is not a
    # sentence, and there is nothing to compare them against as one number.
    assert "чем неделей раньше" not in text


async def test_the_week_before_is_compared_while_one_currency_is_in_play(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    card = await add_card(session, user, "Biedronka", "300", currency="PLN")
    await add_spend(session, card, user, "20", days_ago=2)
    await add_spend(session, card, user, "50", days_ago=10)

    text = await build_digest(session)

    assert "Потратили: 20 PLN" in text
    assert "на 30 меньше" in text


async def test_digest_in_english(session: AsyncSession, monkeypatch):
    """DEFAULT_LANGUAGE switches the family chat, digest included."""
    from app.config import settings

    monkeypatch.setattr(settings, "default_language", "en")
    user = await make_user(session)
    await add_card(session, user, "Rewe", "40")
    await add_card(session, user, "Penny", "10")

    text = await build_digest(session)

    assert "The week in cards" in text
    assert "across 2 of them" in text
    assert "Nothing was spent this week" in text

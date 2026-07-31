"""Statistics, on a database of its own so the numbers are exact.

The API-level tests share one database, which is fine for "did this figure move by
50" but useless for "is this the whole answer". Everything here starts empty.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from app.stats import collect_stats


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/stats.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(User(telegram_id=42, first_name="Аня"))
        await db.flush()
        yield db
    await engine.dispose()


async def only_member(session: AsyncSession) -> User:
    return (await session.execute(select(User))).scalars().one()


async def add_card(
    session: AsyncSession,
    merchant: str,
    balance: str,
    *,
    currency: str = "EUR",
    status: VoucherStatus = VoucherStatus.active,
) -> Voucher:
    card = Voucher(
        created_by_id=(await only_member(session)).id,
        merchant=merchant,
        value_kind=ValueKind.amount,
        value_amount=Decimal(balance),
        balance_amount=Decimal(balance),
        currency=currency,
        status=status,
    )
    session.add(card)
    await session.flush()
    return card


async def add_spend(session: AsyncSession, card: Voucher, amount: str, actor: User | None = None):
    session.add(
        Event(
            voucher_id=card.id,
            actor_id=actor.id if actor else None,
            kind=EventKind.balance_updated,
            payload={"spent": amount, "remaining": "0", "note": ""},
            created_at=utcnow(),
        )
    )
    await session.flush()


async def test_an_empty_family_still_gets_a_page(session: AsyncSession) -> None:
    stats = await collect_stats(session)
    assert [block.currency for block in stats.currencies] == ["EUR"]
    assert stats.currencies[0].on_cards == 0
    assert stats.currencies[0].cards_active == 0
    # Six months of nothing, so the chart has an axis to draw.
    assert len(stats.currencies[0].monthly) == 6


async def test_every_figure_belongs_to_one_currency(session: AsyncSession) -> None:
    euro = await add_card(session, "Rewe", "30")
    zloty = await add_card(session, "Biedronka", "200", currency="PLN")
    await add_spend(session, euro, "10")
    await add_spend(session, zloty, "115.73")

    blocks = {block.currency: block for block in (await collect_stats(session)).currencies}

    assert blocks["EUR"].on_cards == Decimal("30")
    assert blocks["EUR"].spent_total == Decimal("10")
    assert blocks["PLN"].on_cards == Decimal("200")
    assert blocks["PLN"].spent_total == Decimal("115.73")
    assert blocks["EUR"].cards_active == blocks["PLN"].cards_active == 1
    # Each side sees only its own shops and its own months.
    assert [m.merchant for m in blocks["PLN"].by_merchant] == ["Biedronka"]
    assert blocks["EUR"].monthly[-1].spent == Decimal("10")
    assert blocks["PLN"].monthly[-1].spent == Decimal("115.73")


async def test_blocks_are_ordered_by_how_many_cards_they_hold(session: AsyncSession) -> None:
    """Not by amount: ranking currencies by their numbers is the mistake itself.

    A hundred złoty is more than ten euro as a number and less as money.
    """
    await add_card(session, "Biedronka", "999", currency="PLN")
    await add_card(session, "Rewe", "1")
    await add_card(session, "Penny", "1")

    assert [block.currency for block in (await collect_stats(session)).currencies] == [
        "EUR",
        "PLN",
    ]


async def test_a_card_saved_without_a_currency_counts_as_the_default(
    session: AsyncSession,
) -> None:
    """Rows predating the check on the field; a nameless group would be worse."""
    await add_card(session, "Alt", "20", currency="")
    await add_card(session, "Rewe", "5")

    blocks = {block.currency: block for block in (await collect_stats(session)).currencies}

    assert list(blocks) == ["EUR"]
    assert blocks["EUR"].on_cards == Decimal("25")


async def test_archived_and_uncertain_money_stay_in_their_own_currency(
    session: AsyncSession,
) -> None:
    await add_card(session, "Ikea", "40", status=VoucherStatus.archived)
    await add_card(session, "Zabka", "60", currency="PLN", status=VoucherStatus.archived)
    doubtful = await add_card(session, "Orlen", "17", currency="PLN")
    doubtful.balance_uncertain = True
    await session.flush()

    blocks = {block.currency: block for block in (await collect_stats(session)).currencies}

    assert blocks["EUR"].archived_balance == Decimal("40")
    assert blocks["PLN"].archived_balance == Decimal("60")
    assert blocks["PLN"].uncertain_balance == Decimal("17")
    assert blocks["PLN"].on_cards == 0
    assert blocks["EUR"].uncertain_balance == 0

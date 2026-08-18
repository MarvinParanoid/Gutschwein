"""The PRAGMAs SQLite does not set by itself.

Every test takes `client`: it is the fixture that starts the app, and the app is
what runs the migrations these tables come from.

They are per connection, not per database, so a regression here is invisible until
something goes wrong at exactly the wrong moment: a delete that should have been
refused, or a reader blocked behind a writer.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import User, Voucher


async def test_the_connection_is_configured(client: TestClient) -> None:
    async with SessionLocal() as session:
        assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
        assert (await session.execute(text("PRAGMA journal_mode"))).scalar() == "wal"
        assert (await session.execute(text("PRAGMA busy_timeout"))).scalar() == 5000


async def test_a_member_with_history_cannot_be_deleted(client: TestClient) -> None:
    """The bug this replaces: the delete succeeded, and SQLite reused the id.

    The vouchers kept pointing at a row that no longer existed, so the next member
    created inherited them — a card silently changed author.
    """
    async with SessionLocal() as session:
        member = User(first_name="Уходящий")
        session.add(member)
        await session.flush()
        session.add(Voucher(merchant="Наследство", created_by_id=member.id))
        await session.commit()
        member_id = member.id

    async with SessionLocal() as session:
        doomed = await session.get(User, member_id)
        assert doomed is not None
        await session.delete(doomed)
        with pytest.raises(IntegrityError):
            await session.commit()

    async with SessionLocal() as session:
        assert await session.get(User, member_id) is not None


async def test_a_member_who_did_nothing_still_goes(client: TestClient) -> None:
    async with SessionLocal() as session:
        member = User(first_name="Ничего не делал")
        session.add(member)
        await session.commit()
        member_id = member.id

    async with SessionLocal() as session:
        await session.delete(await session.get(User, member_id))
        await session.commit()
        assert await session.get(User, member_id) is None

"""Sweeping credentials that are already refused everywhere else."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.maintenance import cleanup_expired_credentials
from app.models import LoginToken, Session, User, utcnow
from app.sessions import digest


async def _member(name: str) -> int:
    """A member of their own, because tests share one database and one listing."""
    async with SessionLocal() as session:
        member = User(first_name=name)
        session.add(member)
        await session.commit()
        return member.id


async def test_dead_rows_go_and_live_ones_stay(client: TestClient) -> None:
    user_id = await _member("Владелец сессий")
    now = utcnow()
    async with SessionLocal() as session:
        session.add_all(
            [
                Session(
                    token_hash=digest("живая"), user_id=user_id, expires_at=now + timedelta(days=30)
                ),
                Session(
                    token_hash=digest("протухла"),
                    user_id=user_id,
                    expires_at=now - timedelta(days=1),
                ),
                LoginToken(
                    token_hash=digest("свежий"),
                    user_id=user_id,
                    expires_at=now + timedelta(minutes=5),
                ),
                LoginToken(
                    token_hash=digest("просрочен"),
                    user_id=user_id,
                    expires_at=now - timedelta(minutes=5),
                ),
                # Single use is the point, so a spent token is as dead as an old one.
                LoginToken(
                    token_hash=digest("потрачен"),
                    user_id=user_id,
                    expires_at=now + timedelta(minutes=5),
                    used_at=now,
                ),
            ]
        )
        await session.commit()

    async with SessionLocal() as session:
        # Counted, not asserted on: the suite shares one database, so other tests
        # leave their own dead rows for this sweep to find.
        await cleanup_expired_credentials(session)

    async with SessionLocal() as session:
        sessions_left = set((await session.execute(select(Session.token_hash))).scalars())
        tokens_left = set((await session.execute(select(LoginToken.token_hash))).scalars())

    assert digest("живая") in sessions_left
    assert digest("протухла") not in sessions_left
    assert digest("свежий") in tokens_left
    assert digest("просрочен") not in tokens_left
    assert digest("потрачен") not in tokens_left


async def test_an_expired_session_is_not_listed_as_a_signed_in_device(
    client: TestClient,
) -> None:
    """It cannot sign in, so showing it only hides the device that can."""
    user_id = await _member("Вчерашний участник")
    async with SessionLocal() as session:
        session.add(
            Session(
                token_hash=digest("вчерашний браузер"),
                user_id=user_id,
                expires_at=utcnow() - timedelta(days=1),
            )
        )
        await session.commit()

    listed = client.get("/api/auth/sessions").json()
    assert all(row["member"] != "Вчерашний участник" for row in listed)


async def test_a_live_session_is_still_listed(client: TestClient) -> None:
    user_id = await _member("Сегодняшний участник")
    async with SessionLocal() as session:
        session.add(
            Session(
                token_hash=digest("сегодняшний браузер"),
                user_id=user_id,
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        await session.commit()

    listed = client.get("/api/auth/sessions").json()
    assert any(row["member"] == "Сегодняшний участник" for row in listed)

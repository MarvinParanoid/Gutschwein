"""A one-time login link is one session, however many times it is opened at once.

Redeeming used to read the token, check it was unused, and only then mark it used
and commit — with nothing tying the read to the write. Five simultaneous requests
with one link all read "unused" and all opened a session (F5). Consuming the link
and opening the session were also two commits, so a failure between them spent
the link and signed nobody in.
"""

import asyncio
import itertools
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import TelegramUser, upsert_user
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import LoginToken, Session, User
from app.routers import auth as auth_router
from app.sessions import issue_login_token

_ids = itertools.count(990_001)


@pytest.fixture
async def browsers(client: TestClient) -> AsyncIterator:
    """Separate cookie jars, one per device. `client` runs the migrations."""
    opened: list[httpx.AsyncClient] = []

    def open_browser() -> httpx.AsyncClient:
        browser = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver"
        )
        opened.append(browser)
        return browser

    yield open_browser
    for browser in opened:
        await browser.aclose()


async def _member(monkeypatch) -> User:
    telegram_id = next(_ids)
    monkeypatch.setattr(settings, "allowed_telegram_ids", str(telegram_id))
    async with SessionLocal() as db:
        return await upsert_user(db, TelegramUser({"id": telegram_id, "first_name": "Login"}))


async def _link(user: User) -> str:
    async with SessionLocal() as db:
        return await issue_login_token(db, await db.get(User, user.id))


async def _state(user: User) -> tuple[int, list[bool]]:
    """(sessions, [used? for each of their links])."""
    async with SessionLocal() as db:
        sessions = await db.execute(select(Session).where(Session.user_id == user.id))
        tokens = await db.execute(
            select(LoginToken).where(LoginToken.user_id == user.id).order_by(LoginToken.id)
        )
        return len(sessions.all()), [t.used_at is not None for t in tokens.scalars()]


async def _login(browser: httpx.AsyncClient, token: str) -> httpx.Response:
    return await browser.post("/api/auth/login", json={"token": token})


async def test_five_simultaneous_openings_make_one_session(monkeypatch, browsers) -> None:
    """Ten links, each opened five times at once — all fifty requests in one burst,
    so that the interleaving the old code lost to cannot be dodged by luck."""
    user = await _member(monkeypatch)
    links = [await _link(user) for _ in range(10)]

    responses = await asyncio.gather(
        *(_login(browsers(), link) for link in links for _ in range(5))
    )

    for i in range(10):
        five = responses[i * 5 : i * 5 + 5]
        assert sorted(r.status_code for r in five) == [200, 401, 401, 401, 401], f"link {i}"
        winner = next(r for r in five if r.status_code == 200)
        assert winner.cookies.get("gutschwein_session")
        assert all("gutschwein_session" not in r.cookies for r in five if r is not winner)
    assert await _state(user) == (10, [True] * 10)


async def test_a_second_opening_waits_for_the_first_and_is_refused(monkeypatch, browsers) -> None:
    """Forced interleaving: the first request has consumed the link and holds the
    lock when the second arrives; the second must see the link as used."""
    user = await _member(monkeypatch)
    link = await _link(user)
    consumed = asyncio.Event()
    release = asyncio.Event()
    real = auth_router.check_allowed

    async def hold_after_consuming(session, member):
        if not consumed.is_set():
            consumed.set()
            await release.wait()
        return await real(session, member)

    monkeypatch.setattr(auth_router, "check_allowed", hold_after_consuming)
    first = asyncio.create_task(_login(browsers(), link))
    await asyncio.wait_for(consumed.wait(), 5)
    second = asyncio.create_task(_login(browsers(), link))
    await asyncio.sleep(0.2)  # let it queue on the lock; well inside busy_timeout
    assert not second.done()
    release.set()

    assert (await first).status_code == 200
    assert (await second).status_code == 401
    assert await _state(user) == (1, [True])


async def test_a_failed_session_leaves_the_link_unused(monkeypatch, browsers) -> None:
    user = await _member(monkeypatch)
    link = await _link(user)
    real = auth_router.open_session

    async def broken(session, member):
        session.add(Session(token_hash=None, user_id=member.id, expires_at=None))
        return await real(session, member)

    monkeypatch.setattr(auth_router, "open_session", broken)
    with pytest.raises(IntegrityError):
        await _login(browsers(), link)
    assert await _state(user) == (0, [False])

    # Nothing was spent: the same link still works, once.
    monkeypatch.setattr(auth_router, "open_session", real)
    assert (await _login(browsers(), link)).status_code == 200
    assert await _state(user) == (1, [True])


async def test_an_expired_link_stays_refused_under_concurrency(monkeypatch, browsers) -> None:
    user = await _member(monkeypatch)
    link = await _link(user)
    async with SessionLocal() as db:
        row = (
            await db.execute(select(LoginToken).where(LoginToken.user_id == user.id))
        ).scalar_one()
        row.expires_at = row.created_at  # in the past
        await db.commit()

    responses = await asyncio.gather(*(_login(browsers(), link) for _ in range(3)))

    assert [r.status_code for r in responses] == [401] * 3
    assert await _state(user) == (0, [False])


async def test_a_refused_member_gets_no_session_and_spends_the_link(monkeypatch, browsers) -> None:
    """Membership is still checked, and a refused attempt still uses the link up
    (documented in docs/internals.md), once, however many requests carry it."""
    user = await _member(monkeypatch)
    link = await _link(user)
    monkeypatch.setattr(settings, "allowed_telegram_ids", "")

    responses = await asyncio.gather(*(_login(browsers(), link) for _ in range(3)))

    assert sorted(r.status_code for r in responses) == [401, 401, 403]
    assert await _state(user) == (0, [True])


async def test_different_links_are_independent(monkeypatch, browsers) -> None:
    user = await _member(monkeypatch)
    links = [await _link(user) for _ in range(3)]

    responses = await asyncio.gather(*(_login(browsers(), link) for link in links))

    assert [r.status_code for r in responses] == [200] * 3
    assert await _state(user) == (3, [True, True, True])

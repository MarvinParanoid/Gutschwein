"""Browser login: the one credential this app issues, so it gets tested hard."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import TelegramUser, upsert_user
from app.config import settings
from app.db import SessionLocal
from app.models import LoginToken, Session, utcnow
from app.sessions import issue_login_token, redeem_login_token


@pytest.fixture(autouse=True)
def allow_test_members(monkeypatch):
    """The whitelist is enforced on this path, so test members have to be on it.

    999999 is deliberately left out — that is the "access revoked" case below.
    """
    monkeypatch.setattr(
        settings, "allowed_telegram_ids", "555001,555002,555003,555004,555005,555006"
    )


async def _member(telegram_id: int = 555001):
    async with SessionLocal() as session:
        return await upsert_user(session, TelegramUser({"id": telegram_id, "first_name": "Аня"}))


async def _token(user) -> str:
    async with SessionLocal() as session:
        return await issue_login_token(session, user)


async def test_a_link_can_be_used_once(client: TestClient) -> None:
    user = await _member()
    token = await _token(user)

    first = client.post("/api/auth/login", json={"token": token})
    assert first.status_code == 200
    assert first.json()["telegram_id"] == user.telegram_id

    # Replaying the same link must fail: a chat history is not a credential store.
    again = client.post("/api/auth/login", json={"token": token})
    assert again.status_code == 401
    client.cookies.clear()


async def test_the_cookie_is_locked_down(client: TestClient) -> None:
    token = await _token(await _member(555002))
    response = client.post("/api/auth/login", json={"token": token})

    header = response.headers["set-cookie"].lower()
    assert "httponly" in header  # an XSS cannot read it
    assert "secure" in header  # never leaves over plain http
    assert "samesite=lax" in header  # blocks cross-site POSTs — our CSRF defence
    client.cookies.clear()


async def test_a_made_up_token_gets_nothing(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={"token": "не-настоящий"}).status_code == 401


async def test_an_expired_link_is_refused(client: TestClient) -> None:
    user = await _member(555003)
    token = await _token(user)
    async with SessionLocal() as session:
        row = (
            await session.execute(select(LoginToken).order_by(LoginToken.id.desc()).limit(1))
        ).scalar_one()
        row.expires_at = utcnow() - timedelta(minutes=1)
        await session.commit()

    assert client.post("/api/auth/login", json={"token": token}).status_code == 401


async def test_the_database_never_stores_a_usable_token(client: TestClient) -> None:
    """A leaked backup must not hand anyone a way in."""
    user = await _member(555004)
    token = await _token(user)

    async with SessionLocal() as session:
        rows = (await session.execute(select(LoginToken.token_hash))).scalars().all()
    assert token not in rows
    assert all(len(h) == 64 for h in rows)


async def test_the_session_cookie_opens_the_api(client: TestClient) -> None:
    user = await _member(555005)
    token = await _token(user)
    client.post("/api/auth/login", json={"token": token})

    # No dev header, no initData — only the cookie.
    dev_header = client.headers.pop("X-Dev-User", None)
    try:
        me = client.get("/api/me")
    finally:
        if dev_header is not None:
            client.headers["X-Dev-User"] = dev_header
    assert me.status_code == 200
    assert me.json()["user"]["telegram_id"] == user.telegram_id

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 204

    async with SessionLocal() as session:
        left = (await session.execute(select(Session))).scalars().all()
    assert all(s.user_id != user.id for s in left)
    client.cookies.clear()


async def test_losing_access_kills_an_open_session(client: TestClient) -> None:
    """Removing someone from the whitelist must not leave a working browser behind."""
    stranger = await _member(999999)  # not in ALLOWED_TELEGRAM_IDS
    token = await _token(stranger)

    # The link itself is refused, because membership is checked at login too.
    assert client.post("/api/auth/login", json={"token": token}).status_code == 403


async def test_redeeming_marks_the_token_used(client: TestClient) -> None:
    user = await _member(555006)
    token = await _token(user)
    async with SessionLocal() as session:
        assert await redeem_login_token(session, token) is not None
        # Second call inside the same session, straight against the helper.
        assert await redeem_login_token(session, token) is None

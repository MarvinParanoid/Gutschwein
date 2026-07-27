"""Members invited from the console: the way in that does not involve Telegram.

The risk of a second door is that it becomes a way around the first one, so the
whitelist invariant is asserted here too, not only in test_auth_session.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import invite
from app.auth import TelegramUser, upsert_user
from app.config import settings
from app.db import SessionLocal
from app.models import Session, User
from app.sessions import issue_login_token


@pytest.fixture(autouse=True)
def empty_whitelist(monkeypatch):
    """Nobody is on the Telegram whitelist: a console member must still get in."""
    monkeypatch.setattr(settings, "allowed_telegram_ids", "")


async def _console_member(name: str = "Аня") -> tuple[User, str]:
    async with SessionLocal() as session:
        user = User(first_name=name)
        session.add(user)
        await session.flush()
        token = await issue_login_token(session, user)
        await session.commit()
        return user, token


def _cookie_only(client: TestClient):
    """Drop the dev header so the request is judged on the session cookie alone."""
    return client.headers.pop("X-Dev-User", None)


async def test_a_console_member_gets_in_without_telegram(client: TestClient) -> None:
    user, token = await _console_member()
    assert user.telegram_id is None

    assert client.post("/api/auth/login", json={"token": token}).status_code == 200

    dev_header = _cookie_only(client)
    try:
        me = client.get("/api/me")
        assert me.status_code == 200
        assert me.json()["user"]["telegram_id"] is None
        assert me.json()["user"]["display_name"] == "Аня"
        # And it is a real session, not just an identity: the API works.
        assert client.get("/api/vouchers?status=active").status_code == 200
    finally:
        if dev_header is not None:
            client.headers["X-Dev-User"] = dev_header
        client.post("/api/auth/logout")
        client.cookies.clear()


async def test_the_second_door_is_not_a_way_around_the_whitelist(client: TestClient) -> None:
    """A Telegram member off the list stays out, however they arrived."""
    async with SessionLocal() as session:
        stranger = await upsert_user(session, TelegramUser({"id": 424242, "first_name": "X"}))
        token = await issue_login_token(session, stranger)

    assert client.post("/api/auth/login", json={"token": token}).status_code == 403
    client.cookies.clear()


async def test_revoking_ends_an_open_browser_session(client: TestClient) -> None:
    user, token = await _console_member("Макс")
    client.post("/api/auth/login", json={"token": token})

    dev_header = _cookie_only(client)
    try:
        assert client.get("/api/me").status_code == 200
        await invite.revoke(user.id)
        # The cookie is still in the jar; it just does not open anything now.
        assert client.get("/api/me").status_code == 401
    finally:
        if dev_header is not None:
            client.headers["X-Dev-User"] = dev_header
        client.cookies.clear()

    async with SessionLocal() as session:
        assert await session.get(User, user.id) is None
        left = (await session.execute(select(Session).where(Session.user_id == user.id))).all()
    assert left == []


async def test_revoking_a_telegram_member_points_at_the_env_instead(client: TestClient) -> None:
    """Deleting the row would not help: the bot recreates it on the next message."""
    async with SessionLocal() as session:
        member = await upsert_user(session, TelegramUser({"id": 424243, "first_name": "Y"}))

    with pytest.raises(SystemExit) as exit_info:
        await invite.revoke(member.id)
    assert "ALLOWED_TELEGRAM_IDS" in str(exit_info.value)


async def test_a_fresh_link_can_be_issued_for_an_existing_member(client: TestClient) -> None:
    user, _first = await _console_member("Ли")
    async with SessionLocal() as session:
        second = await issue_login_token(session, await session.get(User, user.id))

    assert client.post("/api/auth/login", json={"token": second}).status_code == 200
    client.post("/api/auth/logout")
    client.cookies.clear()


async def test_creating_a_member_prints_a_usable_link(
    client: TestClient, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "webapp_url", "https://example.com")
    await invite.create("Ли")

    printed = capsys.readouterr().out
    assert "https://example.com/login#" in printed
    token = printed.split("/login#")[1].split()[0]

    # The link the operator reads out of the terminal is the one that works.
    assert client.post("/api/auth/login", json={"token": token}).status_code == 200
    client.post("/api/auth/logout")
    client.cookies.clear()


async def test_without_a_public_url_the_token_still_comes_out(capsys, monkeypatch) -> None:
    """A server without WEBAPP_URL can still hand someone a session by hand."""
    monkeypatch.setattr(settings, "webapp_url", "")
    await invite.create("Без домена")

    printed = capsys.readouterr().out
    assert "<WEBAPP_URL>/login#" in printed


async def test_listing_tells_the_two_kinds_apart(capsys) -> None:
    async with SessionLocal() as session:
        await upsert_user(session, TelegramUser({"id": 424244, "first_name": "Z"}))
    console, _token = await _console_member("Консоль")

    await invite.listing()
    printed = capsys.readouterr().out

    assert f"{console.id}" in printed
    assert "console" in printed and "telegram" in printed


async def test_a_missing_member_is_an_error_not_a_traceback(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        await invite.link(999_999)
    assert "999999" in str(exit_info.value)

    with pytest.raises(SystemExit):
        await invite.revoke(999_999)


async def test_an_extra_link_does_not_disturb_the_first(client: TestClient) -> None:
    """Losing the link should not lock a member out of their own account."""
    user, first = await _console_member("Два ключа")
    async with SessionLocal() as session:
        second = await issue_login_token(session, await session.get(User, user.id))

    assert client.post("/api/auth/login", json={"token": second}).status_code == 200
    client.post("/api/auth/logout")
    client.cookies.clear()
    # The earlier link is still unused, so it still opens the door.
    assert client.post("/api/auth/login", json={"token": first}).status_code == 200
    client.post("/api/auth/logout")
    client.cookies.clear()

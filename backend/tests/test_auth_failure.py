"""Why a request was refused, as the client needs to know it (X-Auth-Failure).

The client forgets its offline copy of the household's data when the device is
out, and only then (src/api.ts). The status code cannot say which case it is: a
401 is also an expired Telegram initData, which reopening the Mini App fixes, and
a 403 is also the CSRF check or someone else's comment. So the server names the
reason, and every refusal that is *not* about the device's access carries none.
"""

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal
from app.models import Session, User, utcnow
from app.sessions import issue_login_token
from tests.test_auth import TOKEN, base_fields, sign

HEADER = "x-auth-failure"
TELEGRAM_MEMBER = 151724313


@pytest.fixture(autouse=True)
def telegram(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(settings, "allowed_telegram_ids", str(TELEGRAM_MEMBER))


@pytest.fixture
def browser(client: TestClient):
    """A browser: no dev header, only what it is given."""
    with TestClient(client.app, base_url=str(client.base_url)) as plain:
        yield plain


async def _signed_in(browser: TestClient, name: str) -> User:
    async with SessionLocal() as db:
        member = User(first_name=name, console_root=True)
        db.add(member)
        await db.flush()
        token = await issue_login_token(db, member)
        await db.commit()
    assert browser.post("/api/auth/login", json={"token": token}).status_code == 200
    assert browser.get("/api/me").status_code == 200
    return member


# --- the device is out -------------------------------------------------------------------


async def test_a_session_revoked_elsewhere_is_named(browser) -> None:
    member = await _signed_in(browser, "Failure-Revoked")
    async with SessionLocal() as db:
        for row in (
            await db.execute(select(Session).where(Session.user_id == member.id))
        ).scalars():
            await db.delete(row)
        await db.commit()

    refused = browser.get("/api/vouchers")

    assert refused.status_code == 401
    assert refused.headers[HEADER] == "session-ended"


async def test_an_expired_browser_session_is_named_the_same(browser) -> None:
    """Expired and revoked look alike once expired rows are swept, and for the
    browser they are alike: only a new login link lets it back in."""
    member = await _signed_in(browser, "Failure-Expired")
    async with SessionLocal() as db:
        await db.execute(
            update(Session)
            .where(Session.user_id == member.id)
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await db.commit()

    refused = browser.get("/api/me")

    assert refused.status_code == 401
    assert refused.headers[HEADER] == "session-ended"


def test_a_browser_without_any_credentials_is_signed_out(browser) -> None:
    refused = browser.get("/api/me")

    assert refused.status_code == 401
    assert refused.headers[HEADER] == "signed-out"


async def test_a_member_whose_membership_ended_is_named(browser) -> None:
    member = await _signed_in(browser, "Failure-Membership")
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == member.id).values(revoked_at=utcnow()))
        await db.commit()

    read = browser.get("/api/vouchers")
    write = browser.post("/api/vouchers", json={"merchant": "x"})

    assert (read.status_code, read.headers[HEADER]) == (403, "membership")
    assert (write.status_code, write.headers[HEADER]) == (403, "membership")


def test_a_telegram_member_taken_off_the_list_is_named(browser) -> None:
    stranger = base_fields(user='{"id": 4242, "first_name": "X"}')

    refused = browser.get("/api/me", headers={"Authorization": f"tma {sign(stranger)}"})

    assert refused.status_code == 403
    assert refused.headers[HEADER] == "membership"


# --- recoverable: the device keeps its copy ----------------------------------------------


def test_expired_telegram_data_is_recoverable_not_revoked(browser) -> None:
    stale = base_fields(auth_date=str(int(time.time()) - 99_999))

    refused = browser.get("/api/me", headers={"Authorization": f"tma {sign(stale)}"})

    assert refused.status_code == 401
    assert refused.headers[HEADER] == "telegram-auth"


def test_tampered_telegram_data_is_not_a_revocation_either(browser) -> None:
    forged = sign(base_fields(), token="1:other-bot")

    refused = browser.get("/api/me", headers={"Authorization": f"tma {forged}"})

    assert refused.status_code == 401
    assert refused.headers[HEADER] == "telegram-auth"


def test_valid_telegram_data_beats_a_dead_cookie(browser) -> None:
    """A WebView may still hold a cookie from a browser session; Telegram's own
    identity decides, and the device is not told it is out."""
    browser.cookies.set("gutschwein_session", "long-gone")

    answer = browser.get("/api/me", headers={"Authorization": f"tma {sign(base_fields())}"})

    assert answer.status_code == 200
    assert HEADER not in answer.headers


# --- not about access at all: no reason given --------------------------------------------


def test_a_refused_cross_origin_write_names_no_reason(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "webapp_url", "https://wallet.example.org")

    refused = client.post("/api/vouchers/1/use", headers={"Origin": "https://evil.example.org"})

    assert refused.status_code == 403
    assert HEADER not in refused.headers


def test_someone_elses_comment_names_no_reason(client: TestClient) -> None:
    card = client.post("/api/vouchers", json={"merchant": "Failure-Comment"}).json()
    comment = client.post(
        f"/api/vouchers/{card['id']}/comments",
        json={"text": "mine"},
        headers={"X-Dev-User": "2000"},
    ).json()

    refused = client.delete(f"/api/vouchers/{card['id']}/comments/{comment['id']}")

    assert refused.status_code == 403
    assert HEADER not in refused.headers


def test_a_dead_login_link_names_no_reason(browser) -> None:
    refused = browser.post("/api/auth/login", json={"token": "not-a-token"})

    assert refused.status_code == 401
    assert HEADER not in refused.headers

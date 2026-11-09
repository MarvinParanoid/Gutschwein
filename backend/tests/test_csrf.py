"""Cross-site request forgery from sibling subdomains (T3).

Every app on the server shares one registrable domain, so to a browser they are the
same *site*, and a SameSite=Lax cookie rides along with their POSTs. Before this
check, a page on any sibling could zero a card's balance through `/use` or sign every
device out through `/auth/sessions/others` — with the victim's own session.
"""

import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.csrf import normalize_origin
from app.db import SessionLocal
from app.main import app
from app.models import LoginToken, User, Voucher
from app.sessions import issue_login_token
from tests.test_auth import TOKEN, sign

APP = "https://wallet.example.org"
SIBLING = "https://other.example.org"
DEV = {"X-Dev-User": "1000"}


@pytest.fixture(autouse=True)
def configured(monkeypatch, client: TestClient):
    """`client` is here for its side effect: it runs the migrations."""
    monkeypatch.setattr(settings, "webapp_url", APP)
    monkeypatch.setattr(settings, "trusted_origins", "")


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        yield http


async def _card(api: httpx.AsyncClient, merchant: str) -> int:
    response = await api.post(
        "/api/vouchers",
        headers=DEV,
        json={"merchant": merchant, "value_kind": "amount", "value_amount": "50"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _balance(card: int) -> Decimal:
    async with SessionLocal() as db:
        return (await db.get(Voucher, card)).balance_amount


def _refused(response: httpx.Response) -> bool:
    return response.status_code == 403 and "не со страницы приложения" in response.json()["detail"]


# --- the attack -----------------------------------------------------------------------


async def test_a_sibling_subdomain_cannot_zero_a_card(api) -> None:
    card = await _card(api, "Csrf-Sibling")

    response = await api.post(f"/api/vouchers/{card}/use", headers={**DEV, "Origin": SIBLING})

    assert _refused(response)
    assert await _balance(card) == Decimal("50.00")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/auth/sessions/others"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/vouchers/1/archive"),
        ("DELETE", "/api/vouchers/1"),
        ("PATCH", "/api/vouchers/1"),
    ],
)
async def test_every_state_change_is_covered(api, method: str, path: str) -> None:
    response = await api.request(method, path, headers={**DEV, "Origin": SIBLING}, json={})

    assert _refused(response)


async def test_an_upload_from_a_sibling_is_refused(api) -> None:
    response = await api.post(
        "/api/uploads",
        headers={**DEV, "Origin": SIBLING},
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert _refused(response)


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "garbage",
        "",
        "http://wallet.example.org",  # same host, other scheme
        "https://wallet.example.org:8443",  # same host, other port
        "https://wallet.example.org.evil.net",
        "https://evil.net/https://wallet.example.org",
        "https://user@wallet.example.org",
    ],
)
async def test_anything_but_the_exact_origin_is_refused(api, origin: str) -> None:
    card = await _card(api, f"Csrf-{origin[:12]}")

    response = await api.post(f"/api/vouchers/{card}/use", headers={**DEV, "Origin": origin})

    assert _refused(response)
    assert await _balance(card) == Decimal("50.00")


# --- what must keep working -------------------------------------------------------------


@pytest.mark.parametrize(
    "origin", [APP, "https://WALLET.example.org", "https://wallet.example.org:443"]
)
async def test_the_apps_own_pages_change_data(api, origin: str) -> None:
    card = await _card(api, "Csrf-Own")

    response = await api.post(f"/api/vouchers/{card}/use", headers={**DEV, "Origin": origin})

    assert response.status_code == 200
    assert await _balance(card) == Decimal("0.00")


async def test_reading_is_never_checked(api) -> None:
    response = await api.get("/api/vouchers", headers={**DEV, "Origin": SIBLING})

    assert response.status_code == 200


async def test_a_listed_extra_origin_is_trusted(api, monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_origins", "http://127.0.0.1:5173, http://localhost:5173")
    card = await _card(api, "Csrf-Extra")

    response = await api.post(
        f"/api/vouchers/{card}/use", headers={**DEV, "Origin": "http://localhost:5173"}
    )

    assert response.status_code == 200


# --- no Origin header ---------------------------------------------------------------------


async def test_no_origin_and_no_fetch_metadata_is_not_a_browser(api) -> None:
    """curl, scripts, the tests: nothing of someone else's to forge with."""
    card = await _card(api, "Csrf-NoOrigin")

    response = await api.post(f"/api/vouchers/{card}/use", headers=DEV)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("site", "allowed"),
    [("same-site", False), ("cross-site", False), ("same-origin", True), ("none", True)],
)
async def test_no_origin_falls_back_to_fetch_metadata(api, site: str, allowed: bool) -> None:
    card = await _card(api, f"Csrf-Site-{site}")

    response = await api.post(f"/api/vouchers/{card}/use", headers={**DEV, "Sec-Fetch-Site": site})

    assert (response.status_code == 200) is allowed
    assert _refused(response) is not allowed


async def test_without_any_trusted_origin_browsers_change_nothing(api, monkeypatch) -> None:
    """A misconfigured server fails closed for browsers; non-browser clients still work."""
    monkeypatch.setattr(settings, "webapp_url", "")
    card = await _card(api, "Csrf-Unconfigured")

    refused = await api.post(f"/api/vouchers/{card}/use", headers={**DEV, "Origin": APP})

    assert _refused(refused)
    assert await _balance(card) == Decimal("50.00")


# --- the two ways in ----------------------------------------------------------------------


async def test_the_mini_app_works_from_its_own_origin_and_only_there(api, monkeypatch) -> None:
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(settings, "allowed_telegram_ids", "770777")
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 770777, "first_name": "Mini"}),
    }
    tma = {"Authorization": f"tma {sign(fields)}"}

    own = await api.post(
        "/api/vouchers",
        headers={**tma, "Origin": APP},
        json={"merchant": "Csrf-MiniApp", "value_kind": "amount", "value_amount": "10"},
    )
    foreign = await api.post(
        "/api/vouchers", headers={**tma, "Origin": SIBLING}, json={"merchant": "Csrf-MiniApp-2"}
    )

    assert own.status_code == 201
    assert _refused(foreign)


async def test_a_login_link_works_from_the_app_and_is_not_spent_by_a_sibling(api) -> None:
    async with SessionLocal() as db:
        member = User(first_name="Csrf-Login", console_root=True)
        db.add(member)
        await db.flush()
        token = await issue_login_token(db, member)
        await db.commit()

    forged = await api.post("/api/auth/login", headers={"Origin": SIBLING}, json={"token": token})
    assert _refused(forged)
    async with SessionLocal() as db:
        row = (
            await db.execute(select(LoginToken).where(LoginToken.user_id == member.id))
        ).scalar_one()
        assert row.used_at is None  # refused before the handler: the link is still good

    real = await api.post("/api/auth/login", headers={"Origin": APP}, json={"token": token})
    assert real.status_code == 200
    assert real.cookies.get("gutschwein_session")


# --- the parser -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Wallet.Example.org/", "https://wallet.example.org"),
        ("https://wallet.example.org:443", "https://wallet.example.org"),
        ("http://127.0.0.1:8099", "http://127.0.0.1:8099"),
        ("https://wallet.example.org/app", None),
        ("ftp://wallet.example.org", None),
        ("https://", None),
        ("https://wallet.example.org:99999", None),
        ("null", None),
    ],
)
def test_origins_are_compared_in_one_form(value: str, expected: str | None) -> None:
    assert normalize_origin(value) == expected

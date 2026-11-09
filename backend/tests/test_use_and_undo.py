""" "Used up", its undo, and the amounts a card accepts (T4, T9).

One tap on "used up" spent whatever was left, and "back to active" left the card at
zero: the money was gone from the card and still counted as spent. Now the undo puts
back exactly what "used up" took, with an entry of the opposite sign that names the
payment it reverses — the log shows both, statistics count neither.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.digest import _spent_since
from app.main import app
from app.models import Event, EventKind, Voucher
from app.routers import vouchers as vouchers_router
from app.stats import collect_stats

ANNA = {"X-Dev-User": "1000"}
BORIS = {"X-Dev-User": "2000"}


@pytest.fixture
async def api(client: TestClient) -> AsyncIterator[httpx.AsyncClient]:
    """`client` is here for its side effect: it runs the migrations."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        for member in (ANNA, BORIS):
            assert (await http.get("/api/me", headers=member)).status_code == 200
        yield http


async def _card(api, merchant: str, value: str = "50", currency: str = "EUR") -> int:
    response = await api.post(
        "/api/vouchers",
        headers=ANNA,
        json={
            "merchant": merchant,
            "value_kind": "amount",
            "value_amount": value,
            "currency": currency,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _spend(api, card: int, amount: str, who=ANNA) -> httpx.Response:
    return await api.post(f"/api/vouchers/{card}/balance", headers=who, json={"spent": amount})


async def _state(card: int) -> tuple[str, Decimal, list[Event]]:
    async with SessionLocal() as db:
        voucher = await db.get(Voucher, card)
        events = (
            (await db.execute(select(Event).where(Event.voucher_id == card).order_by(Event.id)))
            .unique()
            .scalars()
            .all()
        )
        return voucher.status, voucher.balance_amount, list(events)


def _ledger_holds(value: Decimal, balance: Decimal, events: list[Event]) -> bool:
    """The balance is the face value minus every entry in the log, reversals included."""
    spent = sum(
        (Decimal(e.payload["spent"]) for e in events if e.kind == EventKind.balance_updated),
        Decimal(0),
    )
    return balance == value - spent


# --- "used up" and its undo -----------------------------------------------------------


async def test_undo_puts_back_exactly_what_used_up_took(api) -> None:
    card = await _card(api, "Undo-Exact")
    assert (await _spend(api, card, "12.30")).status_code == 200

    used = await api.post(f"/api/vouchers/{card}/use", headers=ANNA)
    assert (used.json()["status"], used.json()["balance_amount"]) == ("used", "0.00")
    back = await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)

    assert (back.json()["status"], back.json()["balance_amount"]) == ("active", "37.70")
    status, balance, events = await _state(card)
    assert _ledger_holds(Decimal("50"), balance, events)
    kinds = [(e.kind, e.payload) for e in events]
    payment = next(e for e in events if e.payload.get("spent") == "37.70")
    assert kinds[-3][0] == EventKind.used
    assert kinds[-3][1] == {"balance_before": "37.70", "payment": payment.id}
    assert kinds[-2] == (
        EventKind.balance_updated,
        {"spent": "-37.70", "remaining": "37.70", "note": "", "reverses": payment.id},
    )
    assert kinds[-1] == (EventKind.unused, {"balance_restored": "37.70"})
    # And the card is spendable again.
    assert (await _spend(api, card, "5")).status_code == 200


async def test_an_undone_used_up_is_no_spending_anywhere(api) -> None:
    """Whoever undoes it, and in whichever month: statistics, the digest and the shop
    chips see the real payment and nothing else."""
    card = await _card(api, "Undo-Stats", "40", "PLN")  # a currency of its own
    assert (await _spend(api, card, "15", ANNA)).status_code == 200
    since = datetime.now(UTC) - timedelta(minutes=1)
    assert (await api.post(f"/api/vouchers/{card}/use", headers=ANNA)).status_code == 200
    assert (await api.post(f"/api/vouchers/{card}/unuse", headers=BORIS)).status_code == 200

    async with SessionLocal() as db:
        stats = await collect_stats(db, "ru")
        weekly = await _spent_since(db, since)
    pln = next(block for block in stats.currencies if block.currency == "PLN")
    assert pln.spent_total == Decimal("15")
    assert {m.name: (m.spent, m.payments) for m in pln.by_member} == {
        "Dev 1000": (Decimal("15"), 1)
    }
    assert weekly.get("PLN", Decimal(0)) == Decimal("15")
    chips = await api.get("/api/vouchers/merchants/stats?status=all", headers=ANNA)
    chip = next(c for c in chips.json() if c["merchant"] == "Undo-Stats")
    assert chip["uses"] == 1


async def test_a_second_undo_is_refused_and_changes_nothing(api) -> None:
    card = await _card(api, "Undo-Twice")
    await api.post(f"/api/vouchers/{card}/use", headers=ANNA)
    assert (await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)).status_code == 200
    _status, _balance, events_before = await _state(card)

    again = await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)

    assert again.status_code == 409
    assert again.json()["detail"] == "Карта и так не отмечена использованной"
    assert len((await _state(card))[2]) == len(events_before)


async def test_used_up_and_undo_at_once_leave_one_consistent_card(api) -> None:
    for attempt in range(5):
        card = await _card(api, f"Undo-Race-{attempt}")
        use, unuse = await asyncio.gather(
            api.post(f"/api/vouchers/{card}/use", headers=ANNA),
            api.post(f"/api/vouchers/{card}/unuse", headers=BORIS),
        )
        status, balance, events = await _state(card)
        assert use.status_code == 200
        if unuse.status_code == 200:  # undo came second
            assert (status, balance) == ("active", Decimal("50.00"))
        else:  # undo came first and found nothing to undo
            assert unuse.status_code == 409
            assert (status, balance) == ("used", Decimal("0.00"))
        assert _ledger_holds(Decimal("50"), balance, events)


async def test_two_used_up_taps_spend_once(api) -> None:
    card = await _card(api, "Undo-DoubleTap")

    responses = await asyncio.gather(
        *(api.post(f"/api/vouchers/{card}/use", headers=ANNA) for _ in range(3))
    )

    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    _status, balance, events = await _state(card)
    assert [e.kind for e in events].count(EventKind.balance_updated) == 1
    assert _ledger_holds(Decimal("50"), balance, events)


# --- when there is nothing to put back ----------------------------------------------------


async def test_a_correction_after_used_up_wins_over_the_undo(api) -> None:
    """Someone already read the real number off a receipt: the undo must not overwrite it."""
    card = await _card(api, "Undo-Corrected")
    await api.post(f"/api/vouchers/{card}/use", headers=ANNA)
    fixed = await api.post(f"/api/vouchers/{card}/balance", headers=ANNA, json={"remaining": "10"})
    assert fixed.status_code == 200

    back = await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)

    assert back.json()["balance_amount"] == "10.00"
    _status, balance, events = await _state(card)
    assert not any("reverses" in e.payload for e in events)
    assert _ledger_holds(Decimal("50"), balance, events)


async def test_a_card_emptied_by_payments_comes_back_empty(api) -> None:
    card = await _card(api, "Undo-Emptied", "20")
    assert (await _spend(api, card, "20")).json()["status"] == "used"

    back = await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)

    assert (back.json()["status"], back.json()["balance_amount"]) == ("active", "0.00")


async def test_a_card_marked_used_before_this_change_comes_back_as_it_is(api) -> None:
    """Old `used` events carry no record of what was taken; nothing is guessed."""
    card = await _card(api, "Undo-Legacy")
    await api.post(f"/api/vouchers/{card}/use", headers=ANNA)
    async with SessionLocal() as db:
        await db.execute(
            update(Event)
            .where(Event.voucher_id == card, Event.kind == EventKind.used)
            .values(payload={})
        )
        await db.commit()

    back = await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)

    assert (back.json()["status"], back.json()["balance_amount"]) == ("active", "0.00")


async def test_an_undo_that_fails_to_commit_changes_nothing(api, monkeypatch) -> None:
    card = await _card(api, "Undo-Fails")
    await api.post(f"/api/vouchers/{card}/use", headers=ANNA)
    _s, _b, events_before = await _state(card)
    real = vouchers_router.record_event

    def broken(session, voucher, actor, kind, payload=None):
        event = real(session, voucher, actor, kind, payload)
        if kind == EventKind.unused:
            event.kind = None  # NOT NULL: the commit fails
        return event

    monkeypatch.setattr(vouchers_router, "record_event", broken)
    with pytest.raises(IntegrityError):
        await api.post(f"/api/vouchers/{card}/unuse", headers=ANNA)

    status, balance, events = await _state(card)
    assert (status, balance) == ("used", Decimal("0.00"))
    assert len(events) == len(events_before)


# --- amounts ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("-20", "Сумма не может быть отрицательной"),
        ("12.345", "Не больше двух знаков после запятой"),
        ("100000000", "Слишком большая сумма"),
        ("123456789012345.678", "Слишком большая сумма"),
    ],
)
async def test_a_face_value_outside_the_column_is_refused(api, value: str, message: str) -> None:
    created = await api.post(
        "/api/vouchers",
        headers=ANNA,
        json={"merchant": "Amount-Bad", "value_kind": "amount", "value_amount": value},
    )
    card = await _card(api, f"Amount-Patch-{value[:6]}")
    patched = await api.patch(f"/api/vouchers/{card}", headers=ANNA, json={"value_amount": value})

    for response in (created, patched):
        assert response.status_code == 422
        assert response.json()["detail"][0]["msg"] == message


@pytest.mark.parametrize("value", ["0", "0.01", "12.5", "12.500", "99999999.99"])
async def test_face_values_within_the_column_are_kept(api, value: str) -> None:
    created = await api.post(
        "/api/vouchers",
        headers=ANNA,
        json={"merchant": "Amount-Good", "value_kind": "amount", "value_amount": value},
    )

    assert created.status_code == 201
    assert Decimal(created.json()["value_amount"]) == Decimal(value)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"spent": "0"}, "Потраченная сумма должна быть больше нуля"),
        ({"spent": "-5"}, "Сумма не может быть отрицательной"),
        ({"spent": "0.004"}, "Не больше двух знаков после запятой"),
        ({"spent": "100000000"}, "Слишком большая сумма"),
        ({"remaining": "-1"}, "Сумма не может быть отрицательной"),
        ({"remaining": "1.001"}, "Не больше двух знаков после запятой"),
    ],
)
async def test_a_payment_or_correction_outside_the_rules_writes_nothing(api, body, message) -> None:
    card = await _card(api, f"Amount-Pay-{list(body.values())[0]}")
    _s, _b, events_before = await _state(card)

    response = await api.post(f"/api/vouchers/{card}/balance", headers=ANNA, json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == message
    _s, balance, events = await _state(card)
    assert balance == Decimal("50.00") and len(events) == len(events_before)


async def test_existing_cards_with_out_of_range_amounts_stay_readable(api) -> None:
    """Validation applies to what is sent, not to what is stored."""
    card = await _card(api, "Amount-Legacy")
    async with SessionLocal() as db:
        await db.execute(
            update(Voucher)
            .where(Voucher.id == card)
            .values(value_amount=Decimal("-5"), balance_amount=Decimal("-5"))
        )
        await db.commit()

    response = await api.get(f"/api/vouchers/{card}", headers=ANNA)
    listed = await api.get("/api/vouchers?status=all", headers=ANNA)

    assert response.status_code == 200
    assert response.json()["value_amount"] == "-5.00"
    assert listed.status_code == 200  # one such row must not take the list down

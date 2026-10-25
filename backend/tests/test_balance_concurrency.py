"""Balance changes that arrive at the same time.

Two spends of 10 on a 50 card used to leave 40: both requests read 50 before
either wrote, and each wrote its own answer over the other's — while the event log
recorded both payments. The card and its history then disagreed for good, and the
history is what statistics are summed from.

These requests run concurrently on one event loop, as they do in production (one
uvicorn worker), against the suite's real SQLite database. What has to hold is that
the balance always equals the face value minus everything the log says was spent,
whatever the interleaving.
"""

import asyncio
import io
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app import barcode, quickadd
from app.db import SessionLocal
from app.main import app
from app.models import Event, EventKind, User, Voucher
from app.routers import vouchers as vouchers_router
from app.services import lock_voucher_or_404

ANNA = {"X-Dev-User": "1000"}
BORIS = {"X-Dev-User": "2000"}


@pytest.fixture
async def api(client: TestClient) -> AsyncIterator[httpx.AsyncClient]:
    """`client` is here for its side effect: it runs the migrations."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        # Each member's first request creates their row; two first requests at once
        # race on that insert, which is not what these tests are about.
        for member in (ANNA, BORIS):
            assert (await http.get("/api/me", headers=member)).status_code == 200
        yield http


async def _card(api: httpx.AsyncClient, merchant: str, value: str) -> int:
    response = await api.post(
        "/api/vouchers",
        headers=ANNA,
        json={"merchant": merchant, "value_kind": "amount", "value_amount": value},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _spend(api: httpx.AsyncClient, card: int, amount: str, who=ANNA) -> httpx.Response:
    return await api.post(f"/api/vouchers/{card}/balance", headers=who, json={"spent": amount})


async def _stored(card: int) -> tuple[Voucher, list[Event]]:
    """Straight from the database, past any response the API produced."""
    async with SessionLocal() as db:
        voucher = await db.get(Voucher, card)
        rows = await db.execute(select(Event).where(Event.voucher_id == card).order_by(Event.id))
        return voucher, list(rows.unique().scalars().all())


def _spent(events: list[Event]) -> Decimal:
    return sum(
        (Decimal(e.payload["spent"]) for e in events if e.kind == EventKind.balance_updated),
        Decimal(0),
    )


def _assert_ledger_matches(voucher: Voucher, events: list[Event]) -> None:
    """The card's balance is exactly what its history says is left."""
    assert voucher.balance_amount == voucher.value_amount - _spent(events)
    # Every payment's `remaining` is a balance the card really passed through, in
    # order: each one starts where the previous one ended.
    balance = voucher.value_amount
    for event in events:
        if event.kind != EventKind.balance_updated:
            continue
        balance -= Decimal(event.payload["spent"])
        assert Decimal(event.payload["remaining"]) == balance


async def test_five_concurrent_spends_all_count(api) -> None:
    card = await _card(api, "Concurrent-Five", "50")

    responses = await asyncio.gather(*(_spend(api, card, "10") for _ in range(5)))

    assert [r.status_code for r in responses] == [200] * 5
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("0.00")
    assert voucher.status == "used"
    _assert_ledger_matches(voucher, events)
    kinds = [e.kind for e in events]
    assert kinds.count(EventKind.balance_updated) == 5
    # Emptied once, so closed once.
    assert kinds.count(EventKind.used) == 1
    remaining = sorted(Decimal(r.json()["balance_amount"]) for r in responses)
    assert remaining == [Decimal(n) for n in ("0", "10", "20", "30", "40")]


async def test_two_members_paying_at_once(api) -> None:
    card = await _card(api, "Concurrent-Two", "50")

    responses = await asyncio.gather(
        *(_spend(api, card, "7.25", ANNA) for _ in range(3)),
        *(_spend(api, card, "5.10", BORIS) for _ in range(3)),
    )

    assert [r.status_code for r in responses] == [200] * 6
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("12.95")
    _assert_ledger_matches(voucher, events)
    payments = [e for e in events if e.kind == EventKind.balance_updated]
    assert len(payments) == 6
    assert sorted(e.actor.telegram_id for e in payments) == [1000] * 3 + [2000] * 3


async def test_a_refused_spend_leaves_no_trace(api) -> None:
    """Three of five spends of 20 cannot fit on 50 once the first two went through."""
    card = await _card(api, "Concurrent-Refused", "50")

    responses = await asyncio.gather(*(_spend(api, card, "20") for _ in range(5)))

    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 200, 400, 400, 400]
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("10.00")
    assert voucher.status == "active"
    _assert_ledger_matches(voucher, events)
    assert [e.kind for e in events].count(EventKind.balance_updated) == 2
    # The refusal names the balance as it really was, not the one read before.
    for refused in (r for r in responses if r.status_code == 400):
        assert "10" in refused.json()["detail"]


async def test_correction_and_spend_at_once_stay_consistent(api) -> None:
    """A receipt correction is absolute; its event must still be measured from the
    balance it actually replaced."""
    card = await _card(api, "Concurrent-Correction", "50")

    spend, fix = await asyncio.gather(
        _spend(api, card, "10"),
        api.post(f"/api/vouchers/{card}/balance", headers=BORIS, json={"remaining": "25"}),
    )

    assert (spend.status_code, fix.status_code) == (200, 200)
    voucher, events = await _stored(card)
    # Either order is legitimate: 50→40→25, or 50→25→15.
    assert voucher.balance_amount in (Decimal("25.00"), Decimal("15.00"))
    _assert_ledger_matches(voucher, events)


async def test_concurrent_use_closes_the_card_once(api) -> None:
    card = await _card(api, "Concurrent-Use", "50")

    responses = await asyncio.gather(
        *(api.post(f"/api/vouchers/{card}/use", headers=ANNA) for _ in range(3))
    )

    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("0.00")
    _assert_ledger_matches(voucher, events)
    kinds = [e.kind for e in events]
    assert kinds.count(EventKind.used) == 1
    assert kinds.count(EventKind.balance_updated) == 1


async def test_spends_and_use_at_once(api) -> None:
    card = await _card(api, "Concurrent-SpendUse", "50")

    *spends, use = await asyncio.gather(
        *(_spend(api, card, "10") for _ in range(3)),
        api.post(f"/api/vouchers/{card}/use", headers=BORIS),
    )

    assert use.status_code == 200
    # A spend either lands before the card is closed or is refused after it: never
    # both applied to the same balance.
    assert all(s.status_code in (200, 400) for s in spends)
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("0.00")
    _assert_ledger_matches(voucher, events)
    assert [e.kind for e in events].count(EventKind.used) == 1


async def test_a_failed_event_write_rolls_the_balance_back(api, monkeypatch) -> None:
    card = await _card(api, "Concurrent-Rollback", "50")
    before_voucher, before_events = await _stored(card)
    real = vouchers_router.record_event

    def broken(session, voucher, actor, kind, payload=None):
        event = real(session, voucher, actor, kind, payload)
        if kind == EventKind.balance_updated:
            event.kind = None  # NOT NULL: the INSERT fails inside the commit
        return event

    monkeypatch.setattr(vouchers_router, "record_event", broken)
    with pytest.raises(IntegrityError):
        await _spend(api, card, "50")

    voucher, events = await _stored(card)
    assert voucher.balance_amount == before_voucher.balance_amount == Decimal("50.00")
    assert voucher.status == before_voucher.status
    assert len(events) == len(before_events)

    # …and the lock went with the transaction: the next payment is not stuck behind it.
    monkeypatch.setattr(vouchers_router, "record_event", real)
    assert (await _spend(api, card, "5")).status_code == 200
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("45.00")
    _assert_ledger_matches(voucher, events)


async def test_boundaries(api) -> None:
    card = await _card(api, "Boundary-Card", "20")
    url = f"/api/vouchers/{card}/balance"

    # Exactly the balance: empties it and closes the card.
    assert (await _spend(api, card, "19.99")).status_code == 200
    assert (await _spend(api, card, "0.02")).status_code == 400
    last = await _spend(api, card, "0.01")
    assert last.status_code == 200
    assert last.json()["balance_amount"] == "0.00"
    assert last.json()["status"] == "used"
    # Nothing left: even a cent is refused, and refusals write nothing.
    assert (await _spend(api, card, "0.01")).status_code == 400
    voucher, events = await _stored(card)
    _assert_ledger_matches(voucher, events)
    assert [e.kind for e in events].count(EventKind.balance_updated) == 2

    # A correction may go up to the face value and no further.
    assert (await api.post(url, headers=ANNA, json={"remaining": "20"})).status_code == 200
    assert (await api.post(url, headers=ANNA, json={"remaining": "20.01"})).status_code == 400
    assert (await _spend(api, card, "0")).status_code == 422

    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("20.00")
    _assert_ledger_matches(voucher, events)


async def test_first_spend_on_a_card_without_a_stored_balance(api) -> None:
    """A card turned into a gift card later has a face value but no balance yet."""
    response = await api.post(
        "/api/vouchers", headers=ANNA, json={"merchant": "Boundary-Late", "value_amount": "30"}
    )
    card = response.json()["id"]
    await api.patch(f"/api/vouchers/{card}", headers=ANNA, json={"value_kind": "amount"})
    assert (await _stored(card))[0].balance_amount is None

    responses = await asyncio.gather(_spend(api, card, "10"), _spend(api, card, "5"))

    assert [r.status_code for r in responses] == [200, 200]
    voucher, events = await _stored(card)
    assert voucher.balance_amount == Decimal("15.00")
    _assert_ledger_matches(voucher, events)


# --- Editing the face value while a payment lands -----------------------------
#
# Correcting the face value of an untouched card moves its balance along. That rule
# reads the balance, so PATCH is a read-modify-write too, and it used to judge
# "untouched" from a copy read before a concurrent payment committed: 50 charged 10
# came back as the new face value, the payment gone. The interleavings below are
# forced with explicit gates rather than hoped for with repeated runs.


class LockGate:
    """Holds the next request that reaches the voucher lock, until released.

    That is the exact window the race needs: the request has read the card and done
    its slow work, and has not yet locked it.
    """

    def __init__(self, monkeypatch, module=vouchers_router) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        armed = True

        async def gated(session, voucher_id):
            nonlocal armed
            if armed:
                armed = False
                self.reached.set()
                await self.release.wait()
            return await lock_voucher_or_404(session, voucher_id)

        monkeypatch.setattr(module, "lock_voucher_or_404", gated)

    async def wait(self) -> None:
        await asyncio.wait_for(self.reached.wait(), 5)


class SlowDecoder:
    """A barcode decoder that stops mid-decode until released (it runs in a thread)."""

    FOUND = barcode.Decoded(text="SYNTH-4711", format="Code 128")

    def __init__(self, monkeypatch) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()

        def decode(_data: bytes) -> barcode.Decoded:
            self.reached.set()
            assert self.release.wait(10)
            return self.FOUND

        monkeypatch.setattr(barcode, "decode", decode)


def _last_remaining(events: list[Event]) -> Decimal:
    payments = [e for e in events if e.kind == EventKind.balance_updated]
    return Decimal(payments[-1].payload["remaining"])


async def test_a_payment_before_the_face_value_edit_locks_is_kept(api, monkeypatch) -> None:
    card = await _card(api, "Patch-SpendFirst", "50")
    gate = LockGate(monkeypatch)

    # A has read the untouched card and stops right before locking it…
    edit = asyncio.create_task(
        api.patch(f"/api/vouchers/{card}", headers=ANNA, json={"value_amount": "60"})
    )
    await gate.wait()
    # …B pays and commits…
    spend = await _spend(api, card, "10", BORIS)
    assert spend.status_code == 200
    assert spend.json()["balance_amount"] == "40.00"
    # …and A carries on against what is there now: no longer untouched.
    gate.release.set()
    edited = await edit

    assert edited.status_code == 200
    assert edited.json()["value_amount"] == "60.00"
    assert edited.json()["balance_amount"] == "40.00"
    voucher, events = await _stored(card)
    assert voucher.balance_amount == _last_remaining(events) == Decimal("40.00")
    assert [(e.kind, e.payload.get("fields")) for e in events] == [
        (EventKind.created, None),
        (EventKind.balance_updated, None),
        (EventKind.updated, ["value_amount"]),
    ]


async def test_a_payment_after_the_face_value_edit_spends_from_the_new_value(
    api, monkeypatch
) -> None:
    card = await _card(api, "Patch-EditFirst", "50")
    gate = LockGate(monkeypatch)

    # B has validated its payment and stops right before locking…
    spend = asyncio.create_task(_spend(api, card, "10", BORIS))
    await gate.wait()
    # …A corrects the face value of the still untouched card, balance follows…
    edited = await api.patch(f"/api/vouchers/{card}", headers=ANNA, json={"value_amount": "60"})
    assert edited.json()["balance_amount"] == "60.00"
    # …and B pays from the balance as it is now, not as it was when it started.
    gate.release.set()
    spent = await spend

    assert spent.status_code == 200
    voucher, events = await _stored(card)
    assert voucher.value_amount == Decimal("60.00")
    assert voucher.balance_amount == _last_remaining(events) == Decimal("50.00")
    _assert_ledger_matches(voucher, events)


async def test_a_card_closed_meanwhile_is_not_refilled_by_the_edit(api, monkeypatch) -> None:
    card = await _card(api, "Patch-UsedFirst", "50")
    gate = LockGate(monkeypatch)

    edit = asyncio.create_task(
        api.patch(f"/api/vouchers/{card}", headers=ANNA, json={"value_amount": "60"})
    )
    await gate.wait()
    assert (await api.post(f"/api/vouchers/{card}/use", headers=BORIS)).status_code == 200
    gate.release.set()
    edited = await edit

    assert edited.status_code == 200
    voucher, events = await _stored(card)
    assert voucher.status == "used"
    assert voucher.balance_amount == _last_remaining(events) == Decimal("0.00")


async def test_the_lock_is_not_held_while_a_new_picture_is_decoded(api, monkeypatch) -> None:
    """A payment goes through while the edit is busy decoding, and still counts."""
    card = await _card(api, "Patch-Decode", "50")
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    upload = await api.post(
        "/api/uploads", headers=ANNA, files={"file": ("c.png", buffer.getvalue(), "image/png")}
    )
    image_id = upload.json()["image_id"]
    decoder = SlowDecoder(monkeypatch)

    edit = asyncio.create_task(
        api.patch(
            f"/api/vouchers/{card}",
            headers=ANNA,
            json={"value_amount": "60", "image_id": image_id},
        )
    )
    try:
        assert await asyncio.to_thread(decoder.reached.wait, 5)
        # Were the lock held during the decode, this would wait out busy_timeout (5s).
        spend = await asyncio.wait_for(_spend(api, card, "10", BORIS), 2)
        assert spend.status_code == 200
    finally:
        decoder.release.set()
    edited = await edit

    assert edited.status_code == 200
    body = edited.json()
    assert (body["value_amount"], body["balance_amount"]) == ("60.00", "40.00")
    assert body["image_id"] == image_id
    assert (body["barcode_format"], body["code"]) == ("Code 128", "SYNTH-4711")
    voucher, events = await _stored(card)
    assert voucher.balance_amount == _last_remaining(events) == Decimal("40.00")
    assert [e.kind for e in events].count(EventKind.image_replaced) == 1


async def test_taking_the_lock_changes_nothing_by_itself(api) -> None:
    """No timestamp, no event, no trigger: an edit that changes nothing leaves no mark."""
    card = await _card(api, "Patch-Noop", "50")
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    async with SessionLocal() as db:
        await db.execute(update(Voucher).where(Voucher.id == card).values(updated_at=long_ago))
        await db.commit()
        triggers = await db.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
        assert triggers.all() == []
    _, events_before = await _stored(card)

    # The lock on its own, committed…
    async with SessionLocal() as db:
        await lock_voucher_or_404(db, card)
        await db.commit()
    # …and through an edit that sends the card back unchanged.
    same = await api.patch(
        f"/api/vouchers/{card}", headers=ANNA, json={"merchant": "Patch-Noop", "value_amount": "50"}
    )
    assert same.status_code == 200

    voucher, events = await _stored(card)
    assert voucher.updated_at.replace(tzinfo=UTC) == long_ago
    assert len(events) == len(events_before)


# --- A bot caption completing a draft while it is being spent ------------------
#
# A draft becomes spendable as soon as it has an amount ("50" sent alone, or the
# form), while it still waits for a shop. The next caption used to set the balance
# to its amount outright — erasing whatever had been paid from the draft, whether
# that happened a second or a week earlier. A caption now follows the face-value
# rule of the form: an untouched draft takes the new amount as its balance, a spent
# one keeps what is left.


async def _spendable_draft(api: httpx.AsyncClient, value: str) -> int:
    response = await api.post(
        "/api/vouchers",
        headers=ANNA,
        json={"status": "draft", "value_kind": "amount", "value_amount": value},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _caption(card: int, text: str, *, found: Voucher | None = None) -> bool:
    """What the bot does with a message: find Anna's draft, then apply the caption."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.telegram_id == 1000))).scalar_one()
        voucher = await quickadd.find_pending_draft(db, user)
        assert voucher is not None and voucher.id == card
        return await quickadd.apply_quick_add(db, user, voucher, quickadd.parse_quick_add(text))


async def test_a_caption_on_an_untouched_draft_sets_the_balance(api) -> None:
    card = await _spendable_draft(api, "50")

    assert await _caption(card, "Captionmarkt 60") is True

    voucher, _ = await _stored(card)
    assert (voucher.merchant, voucher.status) == ("Captionmarkt", "active")
    assert voucher.value_amount == voucher.balance_amount == Decimal("60.00")


async def test_a_caption_after_a_payment_keeps_what_is_left(api) -> None:
    card = await _spendable_draft(api, "50")
    assert (await _spend(api, card, "10")).status_code == 200

    assert await _caption(card, "Captionmarkt 60") is True

    voucher, events = await _stored(card)
    assert voucher.status == "active"
    assert voucher.value_amount == Decimal("60.00")
    assert voucher.balance_amount == _last_remaining(events) == Decimal("40.00")


async def test_a_payment_between_finding_the_draft_and_applying_the_caption(api) -> None:
    """The bot has read the draft (find_pending_draft) when the payment commits."""
    card = await _spendable_draft(api, "50")
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.telegram_id == 1000))).scalar_one()
        stale = await quickadd.find_pending_draft(db, user)
        assert stale is not None and stale.balance_amount == Decimal("50.00")

        assert (await _spend(api, card, "10", BORIS)).status_code == 200

        parsed = quickadd.parse_quick_add("Captionmarkt 60")
        assert await quickadd.apply_quick_add(db, user, stale, parsed) is True

    voucher, events = await _stored(card)
    assert voucher.balance_amount == _last_remaining(events) == Decimal("40.00")


async def test_a_payment_waiting_behind_the_caption_spends_from_its_result(
    api, monkeypatch
) -> None:
    card = await _spendable_draft(api, "50")
    gate = LockGate(monkeypatch)

    # The payment has been validated and stops right before locking…
    spend = asyncio.create_task(_spend(api, card, "10", BORIS))
    await gate.wait()
    # …the caption completes the untouched draft…
    assert await _caption(card, "Captionmarkt 60") is True
    gate.release.set()
    # …and the payment is taken from the balance the caption left.
    assert (await spend).status_code == 200

    voucher, events = await _stored(card)
    assert voucher.value_amount == Decimal("60.00")
    assert voucher.balance_amount == _last_remaining(events) == Decimal("50.00")


async def test_a_payment_sent_while_the_caption_holds_the_lock(api, monkeypatch) -> None:
    """The caption has locked the draft; a payment arriving now waits for its commit."""
    card = await _spendable_draft(api, "50")
    locked = asyncio.Event()
    release = asyncio.Event()
    real = quickadd.lock_voucher_or_404

    async def lock_then_hold(session, voucher_id):
        voucher = await real(session, voucher_id)
        locked.set()
        await release.wait()
        return voucher

    monkeypatch.setattr(quickadd, "lock_voucher_or_404", lock_then_hold)
    caption = asyncio.create_task(_caption(card, "Captionmarkt 60"))
    await asyncio.wait_for(locked.wait(), 5)
    spend = asyncio.create_task(_spend(api, card, "10", BORIS))
    # Give the payment the chance to reach the lock and queue on it (well inside
    # busy_timeout). The outcome does not depend on whether it got that far.
    await asyncio.sleep(0.2)
    assert not spend.done()
    release.set()

    assert await caption is True
    assert (await spend).status_code == 200
    voucher, events = await _stored(card)
    assert voucher.balance_amount == _last_remaining(events) == Decimal("50.00")


async def test_a_failed_caption_changes_nothing(api, monkeypatch) -> None:
    card = await _spendable_draft(api, "50")
    assert (await _spend(api, card, "10")).status_code == 200
    before, events_before = await _stored(card)
    real = quickadd.record_event

    def broken(session, voucher, actor, kind, payload=None):
        event = real(session, voucher, actor, kind, payload)
        if kind == EventKind.published:
            event.kind = None  # NOT NULL: the INSERT fails inside the commit
        return event

    monkeypatch.setattr(quickadd, "record_event", broken)
    with pytest.raises(IntegrityError):
        await _caption(card, "Captionmarkt 60")

    voucher, events = await _stored(card)
    assert (voucher.merchant, voucher.status) == (before.merchant, before.status)
    assert (voucher.value_amount, voucher.balance_amount) == (Decimal("50.00"), Decimal("40.00"))
    assert len(events) == len(events_before)
    # The lock went with the failed transaction.
    assert (await _spend(api, card, "5")).status_code == 200

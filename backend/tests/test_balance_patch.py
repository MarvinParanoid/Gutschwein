"""The balance is not an editable field.

PATCH used to accept `balance_amount` and simply set it: no `balance_updated` event,
so the card and its history disagreed, and none of the locking that keeps two
payments from overwriting each other. A balance now changes only through
POST /balance (a payment or a receipt correction) and POST /use, both of which
write the event. A PATCH that still sends the field is refused outright, never
half-applied.
"""

from fastapi.testclient import TestClient

from app.i18n import EN, RU, t


def _gift_card(client: TestClient, merchant: str, value: str = "50") -> dict:
    response = client.post(
        "/api/vouchers",
        json={"merchant": merchant, "value_kind": "amount", "value_amount": value},
    )
    assert response.status_code == 201
    return response.json()


def _events(client: TestClient, card: dict) -> list[dict]:
    return client.get(f"/api/vouchers/{card['id']}/events").json()


def test_patching_the_balance_is_refused(client: TestClient) -> None:
    card = _gift_card(client, "PatchBalance-Refused")

    response = client.patch(f"/api/vouchers/{card['id']}", json={"balance_amount": "10"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == t("error.balance_not_patchable", RU)


def test_patching_the_balance_to_null_is_refused_too(client: TestClient) -> None:
    card = _gift_card(client, "PatchBalance-Null")

    response = client.patch(
        f"/api/vouchers/{card['id']}",
        json={"balance_amount": None},
        headers={"Accept-Language": "en"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == t("error.balance_not_patchable", EN)


def test_a_refused_patch_changes_nothing_at_all(client: TestClient) -> None:
    """Not even the other fields sent alongside: the request is refused whole."""
    card = _gift_card(client, "PatchBalance-Whole")
    client.post(f"/api/vouchers/{card['id']}/balance", json={"spent": "10"})
    before = client.get(f"/api/vouchers/{card['id']}").json()
    history = _events(client, card)

    response = client.patch(
        f"/api/vouchers/{card['id']}",
        json={"merchant": "Renamed", "value_amount": "70", "balance_amount": "70"},
    )

    assert response.status_code == 422
    after = client.get(f"/api/vouchers/{card['id']}").json()
    assert after == before
    assert after["balance_amount"] == "40.00"
    assert _events(client, card) == history


def test_payments_and_corrections_still_go_through_their_endpoint(client: TestClient) -> None:
    card = _gift_card(client, "PatchBalance-Endpoint")
    url = f"/api/vouchers/{card['id']}/balance"

    spent = client.post(url, json={"spent": "12.50", "note": "Kasse"}).json()
    assert spent["balance_amount"] == "37.50"
    corrected = client.post(url, json={"remaining": "40"}).json()
    assert corrected["balance_amount"] == "40.00"

    payments = [e["payload"] for e in _events(client, card) if e["kind"] == "balance_updated"]
    # Newest first: the correction put 2.50 back, the payment took 12.50.
    assert payments == [
        {"spent": "-2.50", "remaining": "40.00", "note": ""},
        {"spent": "12.50", "remaining": "37.50", "note": "Kasse"},
    ]


def test_face_value_edits_behave_as_before(client: TestClient) -> None:
    untouched = _gift_card(client, "PatchBalance-Untouched")
    moved = client.patch(f"/api/vouchers/{untouched['id']}", json={"value_amount": "60"}).json()
    assert (moved["value_amount"], moved["balance_amount"]) == ("60.00", "60.00")

    spent = _gift_card(client, "PatchBalance-Spent")
    client.post(f"/api/vouchers/{spent['id']}/balance", json={"spent": "10"})
    kept = client.patch(f"/api/vouchers/{spent['id']}", json={"value_amount": "60"}).json()
    assert (kept["value_amount"], kept["balance_amount"]) == ("60.00", "40.00")
    assert _events(client, spent)[0]["payload"] == {"fields": ["value_amount"]}


def test_the_other_fields_are_still_editable(client: TestClient) -> None:
    card = _gift_card(client, "PatchBalance-Fields")

    # What the edit form sends: every field of the draft, changed or not.
    form = {
        "merchant": "PatchBalance-Fields2",
        "title": "Geschenkkarte",
        "code": "SYNTH-0001",
        "value_kind": "amount",
        "value_amount": "50",
        "currency": "pln",
        "valid_from": "2026-01-01",
        "valid_until": "2028-12-31",
        "conditions": "online only",
        "notes": "PIN in the drawer",
        "image_id": None,
    }
    edited = client.patch(f"/api/vouchers/{card['id']}", json=form)
    assert edited.status_code == 200
    body = edited.json()
    for field, value in form.items():
        if field in ("currency", "image_id"):
            continue
        assert body[field] == (value if field != "value_amount" else "50.00")
    assert body["currency"] == "PLN"
    assert body["balance_amount"] == "50.00"

    # The doubt toggle on the card is a PATCH of its own and stays one.
    doubted = client.patch(f"/api/vouchers/{card['id']}", json={"balance_uncertain": True})
    assert doubted.json()["balance_uncertain"] is True

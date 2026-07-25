import io
from decimal import Decimal

from fastapi.testclient import TestClient

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def make_voucher(client: TestClient, **overrides) -> dict:
    payload = {
        "merchant": "DM",
        "title": "20% на всё",
        "code": "XK92-7741",
        "value_kind": "percent",
        "value_amount": "20",
        "valid_until": "2030-01-31",
        "conditions": "от 30 EUR",
    } | overrides
    response = client.post("/api/vouchers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_blank_optional_env_values_are_unset() -> None:
    """`.env.example` ships FAMILY_CHAT_ID= empty; that must not crash startup."""
    from app.config import Settings

    assert Settings(family_chat_id="").family_chat_id is None
    assert Settings(family_chat_id="-1001234567890").family_chat_id == -1001234567890


def test_merchant_chips_are_ordered_by_how_often_you_pay_there(client: TestClient) -> None:
    regular = make_voucher(
        client, merchant="Rewe-test", value_kind="amount", value_amount="50", valid_until=None
    )
    make_voucher(
        client, merchant="Aral-test", value_kind="amount", value_amount="50", valid_until=None
    )
    # Two payments at one shop, none at the other.
    client.post(f"/api/vouchers/{regular['id']}/balance", json={"spent": "5"})
    client.post(f"/api/vouchers/{regular['id']}/balance", json={"spent": "5"})

    stats = client.get("/api/vouchers/merchants/stats").json()
    by_name = {s["merchant"]: s for s in stats}
    assert by_name["Rewe-test"]["uses"] == 2
    assert by_name["Aral-test"]["uses"] == 0
    assert by_name["Rewe-test"]["balance"] == "40.00"
    # The shop you actually use comes first.
    names = [s["merchant"] for s in stats]
    assert names.index("Rewe-test") < names.index("Aral-test")


def test_merchant_filter_narrows_the_list(client: TestClient) -> None:
    make_voucher(client, merchant="Penny-test", code="PENNY-1")
    listed = client.get("/api/vouchers", params={"merchant": "Penny-test"}).json()
    assert listed and all(v["merchant"] == "Penny-test" for v in listed)


def test_counts_feed_the_menu(client: TestClient) -> None:
    before = client.get("/api/vouchers/counts").json()

    card = make_voucher(
        client, value_kind="amount", value_amount="40", valid_until=None, merchant="Kaufland"
    )
    client.post(f"/api/vouchers/{card['id']}/balance", json={"remaining": "15"})
    client.post(f"/api/vouchers/{card['id']}/archive")

    after = client.get("/api/vouchers/counts").json()
    assert after["archived"] == before["archived"] + 1
    # Money left on archived cards is what makes the archive worth opening.
    expected = Decimal(before["archived_balance"]) + Decimal("15")
    assert Decimal(after["archived_balance"]) == expected


def test_unknown_paths_are_404_not_the_spa(client: TestClient) -> None:
    """Scanners probe /.env and friends; they must not get a cheerful 200."""
    for path in ("/.env", "/.aws/credentials", "/secrets.yaml", "/info.php"):
        assert client.get(path).status_code == 404, path


def test_me_returns_current_user(client: TestClient) -> None:
    body = client.get("/api/me").json()
    assert body["user"]["telegram_id"] == 1000


def test_auth_required_without_dev_header() -> None:
    from app.main import app

    with TestClient(app) as anon:
        assert anon.get("/api/vouchers").status_code == 401


def test_create_list_and_search(client: TestClient) -> None:
    voucher = make_voucher(client, merchant="Rewe", code="SEARCHME")

    active = client.get("/api/vouchers", params={"status": "active"}).json()
    assert voucher["id"] in [v["id"] for v in active]

    found = client.get("/api/vouchers", params={"q": "searchme"}).json()
    assert [v["id"] for v in found] == [voucher["id"]]

    assert "Rewe" in client.get("/api/vouchers/merchants").json()


def test_upload_and_attach_image(client: TestClient) -> None:
    upload = client.post(
        "/api/uploads",
        files={"file": ("voucher.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["image_id"]

    voucher = make_voucher(client, image_id=image_id)
    assert voucher["image_id"] == image_id

    # Images are served from capability URLs, without the auth header.
    with TestClient(client.app) as anon:
        assert anon.get(f"/api/images/{image_id}").status_code == 200
        assert anon.get("/api/images/2026-01/notarealimage.png").status_code == 404


def test_rejects_non_image_upload(client: TestClient) -> None:
    response = client.post(
        "/api/uploads", files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")}
    )
    assert response.status_code == 415


def test_patch_records_changed_fields(client: TestClient) -> None:
    voucher = make_voucher(client)
    patched = client.patch(
        f"/api/vouchers/{voucher['id']}", json={"notes": "лежит в кошельке"}
    ).json()
    assert patched["notes"] == "лежит в кошельке"

    events = client.get(f"/api/vouchers/{voucher['id']}/events").json()
    kinds = [e["kind"] for e in events]
    assert kinds == ["updated", "created"]
    assert events[0]["payload"] == {"fields": ["notes"]}


def test_status_transitions(client: TestClient) -> None:
    voucher = make_voucher(client)
    vid = voucher["id"]

    used = client.post(f"/api/vouchers/{vid}/use").json()
    assert used["status"] == "used"
    assert used["used_by"]["telegram_id"] == 1000
    assert client.post(f"/api/vouchers/{vid}/use").status_code == 409

    back = client.post(f"/api/vouchers/{vid}/unuse").json()
    assert back["status"] == "active" and back["used_by"] is None

    archived = client.post(f"/api/vouchers/{vid}/archive").json()
    assert archived["status"] == "archived"
    assert vid in [v["id"] for v in client.get("/api/vouchers?status=archived").json()]
    assert vid not in [v["id"] for v in client.get("/api/vouchers?status=active").json()]

    assert client.post(f"/api/vouchers/{vid}/restore").json()["status"] == "active"


def make_gift_card(client: TestClient, amount: str = "50") -> dict:
    return make_voucher(
        client,
        merchant="IKEA",
        title="Подарочная карта",
        value_kind="amount",
        value_amount=amount,
        valid_until=None,
    )


def test_gift_card_starts_at_face_value(client: TestClient) -> None:
    card = make_gift_card(client)
    assert card["value_amount"] == "50.00"
    assert card["balance_amount"] == "50.00"


def test_spending_reduces_balance(client: TestClient) -> None:
    card = make_gift_card(client)
    after = client.post(
        f"/api/vouchers/{card['id']}/balance", json={"spent": "17.35", "note": "лампы"}
    ).json()
    assert after["balance_amount"] == "32.65"
    assert after["status"] == "active"

    event = client.get(f"/api/vouchers/{card['id']}/events").json()[0]
    assert event["kind"] == "balance_updated"
    assert event["payload"] == {"spent": "17.35", "remaining": "32.65", "note": "лампы"}


def test_setting_remaining_from_receipt(client: TestClient) -> None:
    card = make_gift_card(client)
    after = client.post(
        f"/api/vouchers/{card['id']}/balance", json={"remaining": "12.5"}
    ).json()
    assert after["balance_amount"] == "12.50"

    # A correction is just another update; the ledger keeps both.
    corrected = client.post(
        f"/api/vouchers/{card['id']}/balance", json={"remaining": "21"}
    ).json()
    assert corrected["balance_amount"] == "21.00"
    kinds = [e["kind"] for e in client.get(f"/api/vouchers/{card['id']}/events").json()]
    assert kinds.count("balance_updated") == 2


def test_emptying_balance_marks_voucher_used(client: TestClient) -> None:
    card = make_gift_card(client, "20")
    after = client.post(
        f"/api/vouchers/{card['id']}/balance", json={"spent": "20"}
    ).json()
    assert after["balance_amount"] == "0.00"
    assert after["status"] == "used"
    assert after["used_by"]["telegram_id"] == 1000

    kinds = [e["kind"] for e in client.get(f"/api/vouchers/{card['id']}/events").json()]
    assert kinds[:2] == ["used", "balance_updated"]


def test_marking_used_zeroes_the_balance(client: TestClient) -> None:
    card = make_gift_card(client, "30")
    used = client.post(f"/api/vouchers/{card['id']}/use").json()
    assert used["balance_amount"] == "0.00"


def test_balance_validation(client: TestClient) -> None:
    card = make_gift_card(client, "25")
    url = f"/api/vouchers/{card['id']}/balance"

    assert client.post(url, json={"spent": "25.01"}).status_code == 400
    assert client.post(url, json={"remaining": "40"}).status_code == 400
    assert client.post(url, json={"spent": "0"}).status_code == 422
    assert client.post(url, json={"spent": "-5"}).status_code == 422
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"spent": "5", "remaining": "10"}).status_code == 422
    # Untouched by the rejected attempts.
    assert client.get(f"/api/vouchers/{card['id']}").json()["balance_amount"] == "25.00"


def test_balance_only_for_amount_vouchers(client: TestClient) -> None:
    percent = make_voucher(client)
    assert (
        client.post(f"/api/vouchers/{percent['id']}/balance", json={"spent": "5"}).status_code
        == 400
    )
    assert percent["balance_amount"] is None


def test_editing_face_value_moves_untouched_balance(client: TestClient) -> None:
    card = make_gift_card(client, "50")
    fixed = client.patch(
        f"/api/vouchers/{card['id']}", json={"value_amount": "40"}
    ).json()
    assert fixed["balance_amount"] == "40.00"


def test_editing_face_value_keeps_partly_spent_balance(client: TestClient) -> None:
    card = make_gift_card(client, "50")
    client.post(f"/api/vouchers/{card['id']}/balance", json={"spent": "10"})
    fixed = client.patch(
        f"/api/vouchers/{card['id']}", json={"value_amount": "60"}
    ).json()
    assert fixed["balance_amount"] == "40.00"


def test_comments_are_shared_and_deletable_by_author(
    client: TestClient, other_client: TestClient
) -> None:
    vid = make_voucher(client)["id"]

    mine = client.post(f"/api/vouchers/{vid}/comments", json={"text": "взяла себе"})
    assert mine.status_code == 201
    theirs = other_client.post(
        f"/api/vouchers/{vid}/comments", json={"text": "ок, не трогаю"}
    ).json()

    comments = client.get(f"/api/vouchers/{vid}/comments").json()
    assert [c["text"] for c in comments] == ["взяла себе", "ок, не трогаю"]
    assert client.get(f"/api/vouchers/{vid}").json()["comments_count"] == 2

    # Another member's comment stays put; your own can go.
    assert (
        client.delete(f"/api/vouchers/{vid}/comments/{theirs['id']}").status_code == 403
    )
    assert (
        client.delete(f"/api/vouchers/{vid}/comments/{mine.json()['id']}").status_code
        == 204
    )


def test_empty_comment_rejected(client: TestClient) -> None:
    vid = make_voucher(client)["id"]
    assert client.post(f"/api/vouchers/{vid}/comments", json={"text": "   "}).status_code == 422


def test_expiry_flags(client: TestClient) -> None:
    expired = make_voucher(client, valid_until="2020-01-01")
    assert expired["is_expired"] is True
    assert expired["days_left"] < 0

    forever = make_voucher(client, valid_until=None)
    assert forever["is_expired"] is False and forever["days_left"] is None


def test_drafts_are_separate_from_active(client: TestClient) -> None:
    draft = make_voucher(client, status="draft")
    assert draft["id"] in [v["id"] for v in client.get("/api/vouchers?status=draft").json()]
    assert draft["id"] not in [
        v["id"] for v in client.get("/api/vouchers?status=active").json()
    ]


def test_draft_activation(client: TestClient) -> None:
    draft = make_voucher(client, status="draft")
    activated = client.post(f"/api/vouchers/{draft['id']}/activate").json()
    assert activated["status"] == "active"
    # Already active: activating again is a conflict, not a silent no-op.
    assert client.post(f"/api/vouchers/{draft['id']}/activate").status_code == 409
    assert client.get(f"/api/vouchers/{draft['id']}/events").json()[0]["kind"] == "published"


def test_delete_removes_voucher(client: TestClient) -> None:
    vid = make_voucher(client)["id"]
    assert client.delete(f"/api/vouchers/{vid}").status_code == 204
    assert client.get(f"/api/vouchers/{vid}").status_code == 404

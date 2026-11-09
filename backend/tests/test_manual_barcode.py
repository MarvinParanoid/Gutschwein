"""Barcodes for codes typed by hand (Stage 1, checkout).

A plastic card has no screenshot to decode, so the member names the symbology and
the server draws the code. The bars must be exactly the number under them: the
writer would happily pad a short EAN or upper-case a Code 39, and a till reading
a different number from the one printed is worse than no barcode at all.

Codes here are invented; none of them is a real card.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import update

from app import barcode
from app.db import SessionLocal
from app.models import Voucher
from tests.test_barcode import CARD_NUMBER, as_png, render, screenshot_with

# A valid EAN-13 (check digit 1) and the same number with a wrong last digit.
EAN13 = "4006381333931"
EAN13_WRONG = "4006381333932"


# --- the rules ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "fmt"),
    [
        (EAN13, "EAN-13"),
        ("96385074", "EAN-8"),
        ("036000291452", "UPC-A"),
        ("12345678", "ITF"),
        ("GUT-2031 $/+%.", "Code 39"),
        ("Gift-1234 abc!", "Code 128"),
        ("https://example.com/card/1?x=ü", "QR Code"),
        ("ABC-123", "Data Matrix"),
        ("ABC-123", "PDF417"),
        ("ABC-123", "Aztec"),
    ],
)
def test_codes_that_fit_their_format_are_drawn(code: str, fmt: str) -> None:
    assert barcode.problem(code, fmt) is None
    assert barcode.to_svg(code, fmt) is not None


@pytest.mark.parametrize(
    ("code", "fmt", "key"),
    [
        # The writer would compute the check digit or pad with zeros: refused instead,
        # so the bars never carry digits that are not in the code.
        ("400638133393", "EAN-13", "error.barcode_digits"),
        ("40063813339311", "EAN-13", "error.barcode_digits"),
        ("40063813339A1", "EAN-13", "error.barcode_digits"),
        (EAN13_WRONG, "EAN-13", "error.barcode_check_digit"),
        ("96385075", "EAN-8", "error.barcode_check_digit"),
        ("036000291453", "UPC-A", "error.barcode_check_digit"),
        ("1234567", "ITF", "error.barcode_itf"),
        ("12AB", "ITF", "error.barcode_itf"),
        # Lower case would be drawn as upper case: a different code.
        ("gut-2031", "Code 39", "error.barcode_code39"),
        ("Grüße", "Code 128", "error.barcode_code128"),
        ("ПОДАРОК", "Code 128", "error.barcode_code128"),
        ("ABC", "Not A Format", "error.barcode_format_unknown"),
    ],
)
def test_codes_that_do_not_fit_are_refused_with_the_reason(code: str, fmt: str, key: str) -> None:
    problem = barcode.problem(code, fmt)
    assert problem is not None
    assert problem.key == key


def test_the_check_digit_message_names_the_right_digit() -> None:
    problem = barcode.problem(EAN13_WRONG, "EAN-13")
    assert problem is not None
    assert problem.params == {"format": "EAN-13", "digit": 1}
    assert "1" in problem.render("de")


def test_a_format_only_the_decoder_knows_is_not_refused_for_being_unlisted() -> None:
    """A card whose screenshot decoded as Code 93 keeps working when its code is
    corrected: the list is what the form offers, not what the server accepts."""
    assert "Code 93" not in barcode.MANUAL_FORMATS
    assert barcode.problem("ABC-93", "Code 93") is None


# --- through the API ------------------------------------------------------------------------


def _create(client: TestClient, **fields) -> dict:
    response = client.post("/api/vouchers", json={"merchant": "Handkarte", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_typed_code_with_a_format_gets_a_barcode_without_a_picture(client: TestClient) -> None:
    card = _create(client, code=EAN13, barcode_format="EAN-13")

    assert card["image_id"] is None
    assert card["barcode_format"] == "EAN-13"
    assert card["barcode_version"] == barcode.version(EAN13, "EAN-13")

    drawn = client.get(f"/api/vouchers/{card['id']}/barcode?v={card['barcode_version']}")
    assert drawn.status_code == 200
    assert drawn.json()["format"] == "EAN-13"
    assert "<svg" in drawn.json()["svg"]


def test_the_card_barcode_is_for_members_only(client: TestClient) -> None:
    """No capability URL here: an id and a hash of the code would let a stranger
    confirm a guessed code, so the card's own access check guards it."""
    card = _create(client, code="MEMBERS-ONLY-1", barcode_format="Code 128")

    with TestClient(client.app, base_url="https://testserver") as anon:
        response = anon.get(f"/api/vouchers/{card['id']}/barcode?v={card['barcode_version']}")
    assert response.status_code == 401


def test_an_outdated_version_is_refused(client: TestClient) -> None:
    card = _create(client, code="VERSION-1", barcode_format="Code 128")
    old = card["barcode_version"]
    client.patch(f"/api/vouchers/{card['id']}", json={"code": "VERSION-2"})

    assert client.get(f"/api/vouchers/{card['id']}/barcode?v={old}").status_code == 404
    current = client.get(f"/api/vouchers/{card['id']}").json()["barcode_version"]
    assert client.get(f"/api/vouchers/{card['id']}/barcode?v={current}").status_code == 200


def test_a_card_without_a_format_has_no_barcode(client: TestClient) -> None:
    card = _create(client, code="JUST-TEXT")

    assert card["barcode_version"] is None
    assert client.get(f"/api/vouchers/{card['id']}/barcode").status_code == 404


def test_a_wrong_check_digit_is_refused_in_the_readers_language(client: TestClient) -> None:
    before = len(client.get("/api/vouchers?status=all&q=Prüfziffer").json())

    response = client.post(
        "/api/vouchers",
        json={"merchant": "Prüfziffer", "code": EAN13_WRONG, "barcode_format": "EAN-13"},
        headers={"Accept-Language": "de"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "EAN-13: falsche Prüfziffer — die letzte müsste 1 sein. Prüf den Code"
    )
    # Refused means not stored.
    assert len(client.get("/api/vouchers?status=all&q=Prüfziffer").json()) == before


def test_editing_the_code_is_checked_against_the_format(client: TestClient) -> None:
    card = _create(client, code=EAN13, barcode_format="EAN-13")

    refused = client.patch(f"/api/vouchers/{card['id']}", json={"code": "12345"})
    assert refused.status_code == 422
    assert client.get(f"/api/vouchers/{card['id']}").json()["code"] == EAN13

    # Changing both together is fine, and so is choosing no barcode at all.
    both = client.patch(
        f"/api/vouchers/{card['id']}", json={"code": "12345", "barcode_format": "Code 128"}
    )
    assert both.status_code == 200
    plain = client.patch(f"/api/vouchers/{card['id']}", json={"barcode_format": None})
    assert plain.status_code == 200
    assert plain.json()["barcode_version"] is None


def test_an_empty_string_means_no_barcode(client: TestClient) -> None:
    card = _create(client, code="NO-BARS", barcode_format="  ")
    assert card["barcode_format"] is None


def test_a_form_sending_everything_back_does_not_trip_the_check(client: TestClient) -> None:
    """A recognised card whose typed code its format cannot carry has always been
    allowed; saving an unrelated field must not start refusing it now."""
    card = _create(client, code="RECOGNISED")
    async_set_format(card["id"], "EAN-13")  # as a decoded picture would have left it

    saved = client.patch(
        f"/api/vouchers/{card['id']}",
        json={"merchant": "Umbenannt", "code": "RECOGNISED", "barcode_format": "EAN-13"},
    )
    assert saved.status_code == 200
    assert saved.json()["merchant"] == "Umbenannt"


def async_set_format(voucher_id: int, fmt: str) -> None:
    import asyncio

    async def run() -> None:
        async with SessionLocal() as session:
            await session.execute(
                update(Voucher).where(Voucher.id == voucher_id).values(barcode_format=fmt)
            )
            await session.commit()

    asyncio.run(run())


# --- the picture and the hand ---------------------------------------------------------------


def _upload(client: TestClient, image: Image.Image) -> str:
    response = client.post(
        "/api/uploads", files={"file": ("card.png", io.BytesIO(as_png(image)), "image/png")}
    )
    return response.json()["image_id"]


def test_without_a_named_format_the_picture_still_decides(client: TestClient) -> None:
    image_id = _upload(client, screenshot_with(render(CARD_NUMBER)))
    card = _create(client, image_id=image_id)

    assert (card["code"], card["barcode_format"]) == (CARD_NUMBER, "Code 128")


def test_a_named_format_wins_over_the_picture(client: TestClient) -> None:
    image_id = _upload(client, screenshot_with(render(CARD_NUMBER)))
    card = _create(client, image_id=image_id, barcode_format="QR Code")

    # The code still comes from the picture; only the drawing is the member's choice.
    assert (card["code"], card["barcode_format"]) == (CARD_NUMBER, "QR Code")


def test_a_picture_without_a_barcode_keeps_the_chosen_format(client: TestClient) -> None:
    """Adding a photo of the card's front used to wipe the format: the picture had
    nothing readable, and nothing readable meant no barcode."""
    card = _create(client, code="FRONT-PHOTO-1", barcode_format="Code 128")
    image_id = _upload(client, Image.new("RGB", (600, 400), "white"))

    updated = client.patch(f"/api/vouchers/{card['id']}", json={"image_id": image_id}).json()

    assert updated["barcode_format"] == "Code 128"
    assert updated["barcode_version"] == card["barcode_version"]
    # …and the picture's own address draws the same bars.
    assert client.get(f"/api/barcodes/{image_id}?v={card['barcode_version']}").status_code == 200


def test_a_new_picture_with_a_barcode_still_sets_its_format(client: TestClient) -> None:
    card = _create(client, code=CARD_NUMBER, barcode_format="QR Code")
    image_id = _upload(client, screenshot_with(render(CARD_NUMBER)))

    updated = client.patch(f"/api/vouchers/{card['id']}", json={"image_id": image_id}).json()

    assert updated["barcode_format"] == "Code 128"


# --- who may see a hand-typed card's bars -----------------------------------------------------
#
# One household per server (no groups, by design): "isolation" is members against
# everyone else. The bars are the card's code, so they get exactly the card's check,
# and every refusal carries the reason the client purges its caches on.


@pytest.fixture
def telegram_household(monkeypatch):
    from app.config import settings
    from tests.test_auth import TOKEN

    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(settings, "allowed_telegram_ids", "151724313")


@pytest.fixture
def stranger_browser(client: TestClient):
    with TestClient(client.app, base_url=str(client.base_url)) as plain:
        yield plain


def _barcode_path(client: TestClient) -> str:
    card = _create(client, code="HOUSEHOLD-ONLY-1", barcode_format="Code 128")
    return f"/api/vouchers/{card['id']}/barcode?v={card['barcode_version']}"


def test_a_member_of_the_household_gets_the_bars(
    client: TestClient, stranger_browser: TestClient, telegram_household
) -> None:
    from tests.test_auth import base_fields, sign

    path = _barcode_path(client)
    answer = stranger_browser.get(path, headers={"Authorization": f"tma {sign(base_fields())}"})
    assert answer.status_code == 200


def test_someone_outside_the_household_is_refused_and_told_why(
    client: TestClient, stranger_browser: TestClient, telegram_household
) -> None:
    from tests.test_auth import base_fields, sign

    path = _barcode_path(client)
    outsider = sign(base_fields(user='{"id": 4242, "first_name": "Fremd"}'))

    refused = stranger_browser.get(path, headers={"Authorization": f"tma {outsider}"})

    assert refused.status_code == 403
    assert refused.headers["x-auth-failure"] == "membership"
    assert "svg" not in refused.text


def test_without_credentials_the_device_is_told_it_is_out(
    client: TestClient, stranger_browser: TestClient
) -> None:
    refused = stranger_browser.get(_barcode_path(client))

    assert refused.status_code == 401
    assert refused.headers["x-auth-failure"] == "signed-out"


def test_a_member_whose_access_was_revoked_loses_the_bars(
    client: TestClient, stranger_browser: TestClient, telegram_household
) -> None:
    import asyncio

    from app.models import User, utcnow
    from app.sessions import issue_login_token

    async def signed_in_member() -> int:
        async with SessionLocal() as db:
            member = User(first_name="Bald weg", console_root=True)
            db.add(member)
            await db.flush()
            token = await issue_login_token(db, member)
            await db.commit()
            return member.id, token

    member_id, token = asyncio.run(signed_in_member())
    assert stranger_browser.post("/api/auth/login", json={"token": token}).status_code == 200
    path = _barcode_path(client)
    assert stranger_browser.get(path).status_code == 200

    async def revoke() -> None:
        async with SessionLocal() as db:
            await db.execute(update(User).where(User.id == member_id).values(revoked_at=utcnow()))
            await db.commit()

    asyncio.run(revoke())
    refused = stranger_browser.get(path)

    assert refused.status_code == 403
    assert refused.headers["x-auth-failure"] == "membership"


def test_the_capability_route_cannot_be_used_to_reach_a_hand_typed_card(
    client: TestClient, stranger_browser: TestClient
) -> None:
    """A card without a picture has no /api/barcodes address at all: neither its id
    nor its version is a name that route answers to."""
    card = _create(client, code="NO-CAPABILITY-1", barcode_format="Code 128")

    for guess in (str(card["id"]), card["barcode_version"], f"{card['id']}.svg"):
        assert stranger_browser.get(f"/api/barcodes/{guess}").status_code == 404

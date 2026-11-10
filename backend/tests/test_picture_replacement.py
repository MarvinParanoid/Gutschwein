"""Replacing a card's picture re-reads the card.

A picture's code is decoded once and kept; a *new* picture is new evidence, so the
code follows it — that is what was broken: a QR card whose screenshot was swapped
for an EAN-13 barcode kept the QR's URL, the till asked for that URL as EAN-13, the
writer refused, and a broken picture stood where the bars should be. A code a member
typed is not the picture's to take, and stays.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app
from tests.test_barcode import as_png, render, screenshot_with

ANNA = {"X-Dev-User": "1000"}
# A gift card's QR holds the redeem address; its barcode holds the number.
COUPON_URL = "https://coupons.rossmann.de/appcoupon/xJ3-abc?src=app"
EAN13 = "4006381333931"
CARD_NUMBER = "9998887776665"


@pytest.fixture
async def api(client: TestClient) -> AsyncIterator[httpx.AsyncClient]:
    """`client` is here for its side effect: it runs the migrations."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        assert (await http.get("/api/me", headers=ANNA)).status_code == 200
        yield http


def _picture(text: str = "", fmt: str = "QRCode") -> bytes:
    return as_png(screenshot_with(render(text, fmt)))


BLANK = as_png(Image.new("RGB", (600, 400), "white"))


async def _upload(api: httpx.AsyncClient, data: bytes) -> str:
    response = await api.post(
        "/api/uploads", headers=ANNA, files={"file": ("card.png", data, "image/png")}
    )
    assert response.status_code == 200, response.text
    return response.json()["image_id"]


async def _card(api: httpx.AsyncClient, merchant: str, **fields) -> dict:
    response = await api.post("/api/vouchers", headers=ANNA, json={"merchant": merchant, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def _form(card: dict) -> dict:
    """The edit form posts the whole card back, not only what changed.

    `barcode_format` comes back as it was loaded, so the server sees an unchanged
    value — which is exactly the case that used to keep the old code beside the new
    picture's format.
    """
    return {
        field: card[field]
        for field in (
            "merchant",
            "title",
            "code",
            "value_kind",
            "value_amount",
            "currency",
            "valid_from",
            "valid_until",
            "conditions",
            "notes",
            "image_id",
            "barcode_format",
        )
    }
@pytest.mark.parametrize(
    ("text", "fmt", "expected_code", "expected_format"),
    [
        # The report: this pair refuses to draw at all, so the till showed nothing.
        (EAN13, "EAN13", EAN13, "EAN-13"),
        # …and this one draws happily, which is worse: bars that are not its code's.
        (CARD_NUMBER, "Code128", CARD_NUMBER, "Code 128"),
    ],
)
async def test_a_replaced_picture_re_reads_the_code(
    api, text, fmt, expected_code, expected_format
) -> None:
    qr_image = await _upload(api, _picture(text=COUPON_URL))
    card = await _card(api, "Rossmann", image_id=qr_image)
    assert (card["code"], card["barcode_format"]) == (COUPON_URL, "QR Code")

    barcode_image = await _upload(api, _picture(text=text, fmt=fmt))
    saved = await api.patch(
        f"/api/vouchers/{card['id']}",
        headers=ANNA,
        json={**_form(card), "image_id": barcode_image},
    )

    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert (after["code"], after["barcode_format"]) == (expected_code, expected_format)
    # What the till asks the server for now — and could not have before.
    drawn = await api.get(f"/api/barcodes/{barcode_image}?v={after['barcode_version']}")
    assert drawn.status_code == 200


async def test_a_typed_code_is_not_the_pictures_to_take(api) -> None:
    card = await _card(api, "Eingetippt", code="GIFT-9911", image_id=await _upload(api, BLANK))
    assert card["code"] == "GIFT-9911"

    barcode_image = await _upload(api, _picture(text=EAN13, fmt="EAN13"))
    after = (
        await api.patch(
            f"/api/vouchers/{card['id']}",
            headers=ANNA,
            json={**_form(card), "image_id": barcode_image},
        )
    ).json()

    assert after["code"] == "GIFT-9911"
    # The format beside it is the picture's word, as when one is first attached.
    assert after["barcode_format"] == "EAN-13"


async def test_a_picture_with_nothing_in_it_changes_nothing(api) -> None:
    card = await _card(api, "Vorderseite", image_id=await _upload(api, _picture(text=COUPON_URL)))
    before = (card["code"], card["barcode_format"])

    after = (
        await api.patch(
            f"/api/vouchers/{card['id']}",
            headers=ANNA,
            json={**_form(card), "image_id": await _upload(api, BLANK)},
        )
    ).json()

    assert (after["code"], after["barcode_format"]) == before


async def test_without_the_old_picture_there_is_no_witness(api) -> None:
    """A file the sweep has already taken cannot say whose code this was: a code is
    not guessed away, and the till falls back to the picture instead."""
    qr_image = await _upload(api, _picture(text=COUPON_URL))
    card = await _card(api, "Verloren", image_id=qr_image)
    (settings.upload_dir / qr_image).unlink()

    barcode_image = await _upload(api, _picture(text=EAN13, fmt="EAN13"))
    after = (
        await api.patch(
            f"/api/vouchers/{card['id']}",
            headers=ANNA,
            json={**_form(card), "image_id": barcode_image},
        )
    ).json()

    assert after["code"] == COUPON_URL
    assert after["image_id"] == barcode_image


async def test_taking_the_picture_away_keeps_the_code(api) -> None:
    card = await _card(api, "Ohne Bild", image_id=await _upload(api, _picture(text=COUPON_URL)))
    before = (card["code"], card["barcode_format"])

    after = (
        await api.patch(
            f"/api/vouchers/{card['id']}", headers=ANNA, json={**_form(card), "image_id": None}
        )
    ).json()

    assert after["image_id"] is None
    assert (after["code"], after["barcode_format"]) == before
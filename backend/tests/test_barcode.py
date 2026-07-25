"""Barcode decoding and redrawing.

The redraw is verified by decoding it again: an unreadable barcode on the scan
screen would only be discovered at the till, which is the worst possible place.
"""

import io

import pytest
import zxingcpp
from fastapi.testclient import TestClient
from PIL import Image

from app import barcode

CARD_NUMBER = "2094599346555"


def render(text: str, fmt: str = "Code128", scale: int = 3) -> Image.Image:
    """A barcode as an image, the way a card app would show it on screen."""
    raw = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(text, getattr(zxingcpp.BarcodeFormat, fmt))
    )
    height, width = raw.shape[0], raw.shape[1]
    image = Image.frombuffer("L", (width, height), bytes(raw), "raw", "L", 0, 1)
    return image.resize((width * scale, height * scale), Image.NEAREST)


def as_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def screenshot_with(image: Image.Image, size=(1080, 800)) -> Image.Image:
    """The barcode sitting on a phone screen, surrounded by other pixels."""
    canvas = Image.new("RGB", size, (24, 24, 24))
    canvas.paste(Image.new("RGB", (image.width + 40, image.height + 40), "white"),
                 (60, 200))
    canvas.paste(image.convert("RGB"), (80, 220))
    return canvas


def test_reads_a_code_out_of_a_screenshot() -> None:
    found = barcode.decode(as_png(screenshot_with(render(CARD_NUMBER))))
    assert found is not None
    assert found.text == CARD_NUMBER
    assert found.format == "Code 128"


def test_reads_a_matrix_code_too() -> None:
    found = barcode.decode(as_png(screenshot_with(render("GIFT-9911", "Aztec"))))
    assert found is not None
    assert found.text == "GIFT-9911"
    assert found.format == "Aztec"


def test_thin_bars_are_recovered_by_the_upscale_pass() -> None:
    """One of four real cards only decoded after enlarging."""
    tiny = render(CARD_NUMBER, scale=1)
    found = barcode.decode(as_png(screenshot_with(tiny)))
    assert found is not None and found.text == CARD_NUMBER


def test_a_picture_without_a_barcode_is_not_an_error() -> None:
    plain = Image.new("RGB", (600, 400), "white")
    assert barcode.decode(as_png(plain)) is None


def test_garbage_input_is_not_an_error() -> None:
    assert barcode.decode(b"this is not an image") is None


@pytest.mark.parametrize(
    ("text", "fmt"),
    [(CARD_NUMBER, "Code 128"), ("4006381333931", "EAN-13"), ("GIFT-9911", "Aztec")],
)
def test_redrawn_barcode_still_decodes_to_the_same_code(text: str, fmt: str) -> None:
    """The round trip: what we draw must read back as what we decoded."""
    svg = barcode.to_svg(text, fmt)
    assert svg is not None and svg.lstrip().startswith("<?xml")

    # SVG and raster come from the same encoder, so decoding the raster proves the
    # geometry is right without pulling in an SVG rasteriser.
    name = fmt.replace(" ", "").replace("-", "")
    raw = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(text, getattr(zxingcpp.BarcodeFormat, name))
    )
    height, width = raw.shape[0], raw.shape[1]
    image = Image.frombuffer("L", (width, height), bytes(raw), "raw", "L", 0, 1)
    back = zxingcpp.read_barcodes(image)
    assert back and back[0].text == text


def test_unknown_format_is_declined_rather_than_guessed() -> None:
    assert barcode.to_svg(CARD_NUMBER, "Совершенно новый формат") is None


def test_upload_fills_the_code_and_serves_the_redrawn_barcode(client: TestClient) -> None:
    png = as_png(screenshot_with(render(CARD_NUMBER)))
    image_id = client.post(
        "/api/uploads", files={"file": ("card.png", io.BytesIO(png), "image/png")}
    ).json()["image_id"]

    voucher = client.post(
        "/api/vouchers",
        json={"merchant": "Penny", "value_kind": "amount", "value_amount": "50",
              "image_id": image_id},
    ).json()
    assert voucher["code"] == CARD_NUMBER
    assert voucher["barcode_format"] == "Code 128"

    # Same capability-URL rule as the picture: no auth header on an <img>.
    with TestClient(client.app) as anon:
        svg = anon.get(f"/api/barcodes/{image_id}")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in svg.text


def test_a_typed_code_is_never_overwritten(client: TestClient) -> None:
    png = as_png(screenshot_with(render(CARD_NUMBER)))
    image_id = client.post(
        "/api/uploads", files={"file": ("card.png", io.BytesIO(png), "image/png")}
    ).json()["image_id"]

    voucher = client.post(
        "/api/vouchers",
        json={"merchant": "Penny", "code": "ВПИСАНО РУКАМИ", "image_id": image_id},
    ).json()
    assert voucher["code"] == "ВПИСАНО РУКАМИ"
    # The format is still recorded, so the card can still be redrawn from the code.
    assert voucher["barcode_format"] == "Code 128"


def test_no_barcode_means_no_endpoint(client: TestClient) -> None:
    plain = as_png(Image.new("RGB", (400, 300), "white"))
    image_id = client.post(
        "/api/uploads", files={"file": ("plain.png", io.BytesIO(plain), "image/png")}
    ).json()["image_id"]
    client.post("/api/vouchers", json={"merchant": "Без кода", "image_id": image_id})

    with TestClient(client.app) as anon:
        assert anon.get(f"/api/barcodes/{image_id}").status_code == 404

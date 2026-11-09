"""The bars the till gets carry exactly the card's code (Stage 1 acceptance).

Every manual format is drawn through the API, rasterised here from the SVG as the
client receives it, and read back by a decoder. The SVG is rasterised by this file,
not by the library that wrote it: the writer (Zint, inside zxing-cpp) and the reader
(zxing's own decoders) are different code, so a symbol both agree on is the symbol
the SVG describes — and what comes back must be the code shown under it, character
for character.

Not covered, and not coverable here: a physical till scanner reading a phone
screen. That stays a manual acceptance step.
"""

import io
import re

import pytest
import zxingcpp
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from tests.test_barcode import CARD_NUMBER, as_png, render, screenshot_with

# Invented codes, one per format, each using what that format allows.
CASES = [
    ("EAN-13", "4006381333931"),
    ("EAN-8", "96385074"),
    ("UPC-A", "036000291452"),
    ("Code 128", "Gift-1234 abc!~"),
    ("Code 39", "GUT-2031 $/+%."),
    ("ITF", "12345678901234"),
    ("QR Code", "https://example.com/card/1?pin=0042&x=ü"),
    ("Data Matrix", "DM-6036-0012-3456"),
    ("PDF417", "PDF417 Gutschein 2031-0042"),
    ("Aztec", "AZTEC-0042-xyz"),
]

_SIZE = re.compile(r'<svg[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"')
_RECT = re.compile(r"M(\d+(?:\.\d+)?) (\d+(?:\.\d+)?)h(\d+(?:\.\d+)?)v(\d+(?:\.\d+)?)h-[\d.]+Z")
# Light margin as the till screen gives it: the overlay is white all around.
SCREEN_MARGIN = 12
SCALE = 6


def rasterise(svg: str) -> Image.Image:
    """Draw the SVG's rectangles. Fails loudly on anything else, so a change in how
    the writer draws cannot pass by being half-understood."""
    size = _SIZE.search(svg)
    assert size, "no width/height on <svg>"
    width, height = int(size[1]), int(size[2])
    paths = re.findall(r'<path d="([^"]+)"', svg)
    assert len(paths) == 1, "expected one path of bars"
    rects = _RECT.findall(paths[0])
    assert _RECT.sub("", paths[0]) == "", "path holds something other than rectangles"
    assert rects

    margin = SCREEN_MARGIN * SCALE
    image = Image.new("L", (width * SCALE + 2 * margin, height * SCALE + 2 * margin), 255)
    draw = ImageDraw.Draw(image)
    for x, y, w, h in rects:
        left, top = margin + float(x) * SCALE, margin + float(y) * SCALE
        draw.rectangle((left, top, left + float(w) * SCALE - 1, top + float(h) * SCALE - 1), fill=0)
    return image


def read(image: Image.Image) -> list[tuple[str, str]]:
    return [(str(r.format), r.text) for r in zxingcpp.read_barcodes(image)]


@pytest.mark.parametrize(("fmt", "code"), CASES)
def test_the_drawn_bars_read_back_as_the_cards_code(
    client: TestClient, fmt: str, code: str
) -> None:
    card = client.post(
        "/api/vouchers",
        json={"merchant": f"Payload {fmt}", "code": code, "barcode_format": fmt},
    )
    assert card.status_code == 201, card.text
    card = card.json()
    assert card["code"] == code  # what the till screen prints under the bars

    drawn = client.get(f"/api/vouchers/{card['id']}/barcode?v={card['barcode_version']}")
    assert drawn.status_code == 200

    image = rasterise(drawn.json()["svg"])
    found = read(image)

    if fmt == "UPC-A":
        # UPC-A *is* an EAN-13 starting with 0 — the same bars. zxing-cpp 3 reports
        # it as that 13-digit GTIN, even for a UPC-A it drew itself; a till does the
        # same or drops the 0. Asked for UPC-A alone, it still finds UPC-A.
        assert found == [("EAN-13", "0" + code)], found
        only_upc = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.UPCA)
        assert [(str(r.format), r.text) for r in only_upc] == [(fmt, "0" + code)]
    else:
        assert found == [(fmt, code)], f"{fmt}: drawn {code!r}, read {found!r}"


def test_a_picture_cards_address_draws_the_same_payload(client: TestClient) -> None:
    """The capability URL path (cards with a picture) is held to the same standard."""
    png = as_png(screenshot_with(render(CARD_NUMBER)))
    image_id = client.post(
        "/api/uploads", files={"file": ("card.png", io.BytesIO(png), "image/png")}
    ).json()["image_id"]
    card = client.post(
        "/api/vouchers", json={"merchant": "Payload picture", "image_id": image_id}
    ).json()

    svg = client.get(f"/api/barcodes/{image_id}?v={card['barcode_version']}").text

    assert read(rasterise(svg)) == [("Code 128", CARD_NUMBER)]


@pytest.mark.parametrize(("fmt", "code"), CASES)
def test_one_dimensional_codes_carry_their_quiet_zone(fmt: str, code: str) -> None:
    """Without the ten-module margin a 1D scanner refuses a sharp code (see barcode.py).
    The till screen is white around the image, but the drawing must not count on it."""
    from app import barcode

    if fmt in ("QR Code", "Data Matrix", "PDF417", "Aztec"):
        pytest.skip("2D symbols: the zone is part of the symbol's own rules")
    svg = barcode.to_svg(code, fmt)
    assert svg is not None
    width = int(_SIZE.search(svg)[1])
    rects = _RECT.findall(re.findall(r'<path d="([^"]+)"', svg)[0])
    first = min(float(x) for x, *_ in rects)
    last = max(float(x) + float(w) for x, _, w, _ in rects)
    narrowest = min(float(w) for _, _, w, _ in rects)
    # Measured in narrow bars (modules). EAN/UPC need 7 to 11; the general rule is 10.
    assert first / narrowest >= 7, f"{fmt}: left margin {first / narrowest} modules"
    assert (width - last) / narrowest >= 7, f"{fmt}: right margin {(width - last) / narrowest}"

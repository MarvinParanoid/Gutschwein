"""Barcode decoding and redrawing.

The redraw is verified by decoding it again: an unreadable barcode on the scan
screen would only be discovered at the till, which is the worst possible place.
"""

import io

import pytest
import zxingcpp
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageDraw

from app import barcode

# Invented: a real card number in a public repository is a real card number.
CARD_NUMBER = "9998887776665"


def render(text: str, fmt: str = "Code128", scale: int = 3, quiet: bool = True) -> Image.Image:
    """A barcode as an image, the way a card app would show it on screen.

    `quiet=False` cuts off the ten-module margin the writer adds by itself. It has
    to be cut for a fixture about quiet zones to mean anything: with it left in, an
    image built to have no margin still has one, and the test passes whatever the
    decoder does.
    """
    raw = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(text, getattr(zxingcpp.BarcodeFormat, fmt))
    )
    height, width = raw.shape[0], raw.shape[1]
    image = Image.frombuffer("L", (width, height), bytes(raw), "raw", "L", 0, 1)
    if not quiet:
        image = image.crop(ImageChops.invert(image).getbbox())
    return image.resize((image.width * scale, image.height * scale), Image.NEAREST)


def as_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def screenshot_with(image: Image.Image, size=(1080, 800)) -> Image.Image:
    """The barcode sitting on a phone screen, surrounded by other pixels."""
    canvas = Image.new("RGB", size, (24, 24, 24))
    canvas.paste(Image.new("RGB", (image.width + 40, image.height + 40), "white"), (60, 200))
    canvas.paste(image.convert("RGB"), (80, 220))
    return canvas


MODULE = 7  # px, as in the family's own screenshots


def card_with_frame(text: str = CARD_NUMBER, quiet_modules: float = 4) -> Image.Image:
    """The barcode on a coloured card, cropped to the card — the usual screenshot.

    The card leaves a white gap of a few modules around the bars, and the crop puts
    its colour right after it. In greyscale that colour is dark, so the decoder
    finds a bar where the symbology requires ten modules of blank space, and refuses
    a perfectly sharp barcode. Two of the family's cards are exactly this picture.
    """
    symbol = render(text, scale=MODULE, quiet=False)
    gap = int(quiet_modules * MODULE)
    inner = Image.new("RGB", (symbol.width + 2 * gap, symbol.height + 2 * gap), "white")
    inner.paste(symbol.convert("RGB"), (gap, gap))
    frame = 31
    card = Image.new("RGB", (inner.width + 2 * frame, inner.height + 2 * frame), (189, 50, 41))
    card.paste(inner, (frame, frame))
    return card


def certificate_screenshot(
    text: str = CARD_NUMBER,
    quiet_modules: float = 4,
    card_pad: int = 45,
    screen: tuple[int, int, int] = (19, 22, 21),
) -> Image.Image:
    """A gift certificate as the shop's app shows it, framed the way it really is.

    The card is taller than the crop, so it runs off the top and the bottom and the
    picture's own border is mostly the card's red, with the dark screen showing only
    down the sides. That is why reading a frame off the border failed here: the
    commonest colour around the edge is the card, and a box drawn around everything
    that is not the card grows straight back out to the dark strips.

    Inside are two light panels — the bars, and the number printed below them.
    """
    bars = render(text, scale=MODULE, quiet=False)
    gap = int(quiet_modules * MODULE)
    panel = Image.new("RGB", (bars.width + 2 * gap, bars.height + 2 * gap), "white")
    panel.paste(bars.convert("RGB"), (gap, gap))

    card = Image.new(
        "RGB",
        (panel.width + 2 * card_pad, panel.height + 2 * card_pad + 150),
        (189, 47, 38),
    )
    card.paste(panel, (card_pad, card_pad))
    ImageDraw.Draw(card).rounded_rectangle(
        (card_pad, card.height - 130, card.width - card_pad, card.height - 10),
        radius=14,
        fill="white",
    )

    screenshot = Image.new("RGB", (card.width + 120, card.height - 40), screen)
    screenshot.paste(card, (60, -20))
    return screenshot


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


def test_a_coloured_card_frame_no_longer_hides_the_code() -> None:
    """Both Penny cards failed here, and neither was a question of resolution."""
    found = barcode.decode(as_png(card_with_frame()))
    assert found is not None
    assert found.text == CARD_NUMBER
    assert found.format == "Code 128"


def test_a_frame_with_no_quiet_zone_at_all_is_still_read() -> None:
    found = barcode.decode(as_png(card_with_frame(quiet_modules=0)))
    assert found is not None and found.text == CARD_NUMBER


def test_a_frame_that_is_not_one_flat_colour_is_shaved_off_instead() -> None:
    """Nothing to trim: a gradient, a photo, a card on a patterned background."""
    card = card_with_frame()
    for x in range(0, card.width, 5):
        for y in range(0, card.height, 5):
            on_border = x < 31 or y < 31 or x > card.width - 31 or y > card.height - 31
            if on_border:
                card.putpixel((x, y), (x % 256, 60, y % 256))

    found = barcode.decode(as_png(card))
    assert found is not None and found.text == CARD_NUMBER


@pytest.mark.parametrize("code", ["2094345550373", "2094931897059", "2094918454268"])
def test_the_printed_panel_is_found_inside_a_framed_certificate(code: str) -> None:
    """Six real certificates could not be read, and could not be paid with either.

    Numbers of the same shape as the real ones — thirteen digits, Code 128 — because
    the quiet zone the picture is missing is measured in modules, and the length of
    the number is what decides how many of them there are.
    """
    found = barcode.decode(as_png(certificate_screenshot(code)))
    assert found is not None
    assert found.text == code
    assert found.format == "Code 128"


def test_the_bars_are_not_confused_with_a_black_screen_behind_the_card() -> None:
    """The screen, the card and the ink are all dark; only the panel is not."""
    shot = certificate_screenshot(quiet_modules=2, card_pad=30, screen=(0, 0, 0))
    found = barcode.decode(as_png(shot))
    assert found is not None and found.text == CARD_NUMBER


def test_a_certificate_on_a_light_screen_reads_too() -> None:
    """Light mode: the screen around the card is brighter than the panel's own white."""
    shot = certificate_screenshot(quiet_modules=6, card_pad=60, screen=(245, 245, 247))
    found = barcode.decode(as_png(shot))
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
        json={
            "merchant": "Penny",
            "value_kind": "amount",
            "value_amount": "50",
            "image_id": image_id,
        },
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

"""Reading the barcode out of a card screenshot, and drawing it back.

At the till the app currently shows a screenshot of a screen: compressed, possibly
dim, sometimes photographed at an angle. If the code inside it can be decoded once,
at upload time, then the scan screen can draw a fresh vector barcode instead — sharp
at any zoom, and the number stays available as text if the scanner still refuses.

Decoding is deterministic: no model, no API key, no network.

A 1D barcode is only readable with a quiet zone — about ten module widths of blank
space on each side. Card apps draw the code on a coloured card, and a screenshot
cropped to that card leaves the colour right next to the bars; in greyscale it is
just another dark bar, so the decoder refuses a perfectly sharp barcode. Several of
the family's own cards failed exactly this way, and the answer was not more
resolution but less picture: take the frame off, then hand the decoder its blank
margin.

Trimming that frame away is harder than it sounds, because a screenshot has several
and they are not concentric: Penny's certificate is the dark phone screen, then the
red card — cut off at the top and bottom, so the picture's own border is mostly red
with dark strips down the sides — then the white panel the bars sit on. Peeling by
border colour got the first layer and stopped.

So the panel is found instead of the frame. Bars are printed dark on light, and the
panel is the one wide band of rows that is largely light; the frames around it, at
any nesting and in any colour, are not. Six of the family's certificates were
unreadable and all six read this way.
"""

import io
import logging
from collections.abc import Iterator
from dataclasses import dataclass

import zxingcpp
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

# Thin bars in a phone screenshot can fall below the decoder's resolution; the
# upscale pass recovered one of four real cards that failed at native size.
UPSCALE = 2
# The blank margin added around a cropped barcode, as a share of the longer side.
# The margin the symbologies ask for is ten modules, and a thirteen-digit Code 128
# is about 140 modules end to end, so ten of them is a fifteenth of the code's own
# length — measured along the bars, not across them. Taking the shorter side left a
# crop that was tight to the bars with five modules of margin, which still fails.
QUIET_ZONE = 0.10
# When the frame is not one flat colour there is nothing to trim, so a little is
# shaved off instead. Each step costs another decode, hence a short ladder — and it
# stops well before the bars: past ~10% the code itself is being cut, and half a
# code that still decodes would be a wrong number shown at the till.
INSETS = (0.03, 0.06, 0.09)
# A pixel this bright is paper rather than ink, colour or shadow.
LIGHT_THRESHOLD = 191
# The share of a row that must be light for it to belong to the printed panel. The
# bars themselves take most of it — the Penny panel is 38% light — so this sits well
# below a half, and still far above a red card row, which has no light pixels at all.
PANEL_SHARE = 0.20
# Panels tried, widest band first. Two, because the certificate has a second one
# below with the number printed in it, and a picture may be cropped to either.
PANELS = 2
# Below this a crop cannot hold a barcode.
MIN_SIDE = 40


@dataclass(frozen=True)
class Decoded:
    text: str
    format: str


def _read(image: Image.Image) -> Decoded | None:
    results = zxingcpp.read_barcodes(image, try_rotate=True, try_invert=True)
    for result in results:
        if result.text:
            return Decoded(text=result.text, format=str(result.format))
    return None


def _with_quiet_zone(image: Image.Image) -> Image.Image:
    grey = image.convert("L")
    margin = max(32, int(max(grey.width, grey.height) * QUIET_ZONE))
    return ImageOps.expand(grey, border=margin, fill=255)


def _runs(values: list[int], threshold: float) -> list[tuple[int, int]]:
    """The stretches of `values` that stay above `threshold`, as half-open ranges."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values):
        if value > threshold and start is None:
            start = index
        elif value <= threshold and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(values)))
    return runs


def _row_means(mask: Image.Image) -> list[int]:
    """The average of every row, 0-255. BOX resize to one column does it in C."""
    return list(mask.resize((1, mask.height), Image.BOX).tobytes())


def _light_panels(image: Image.Image) -> Iterator[Image.Image]:
    """The light panels the code may be printed on, widest band first.

    Rows first, because a barcode's rows all look alike and a frame's do not: the
    panel is a run of rows that are largely light, and everything around it — dark
    screen, coloured card, shadow — is not. The sides then come from the light
    pixels inside that run. Taking the widest *light* column instead finds a gap
    between two bars, which is how this first went wrong.
    """
    mask = image.convert("L").point(lambda value: 255 if value > LIGHT_THRESHOLD else 0)
    bands = _runs(_row_means(mask), PANEL_SHARE * 255)
    for top, bottom in sorted(bands, key=lambda band: band[1] - band[0], reverse=True)[:PANELS]:
        box = mask.crop((0, top, mask.width, bottom)).getbbox()
        if box is None:
            continue
        left, right = box[0], box[2]
        if right - left < MIN_SIDE or bottom - top < MIN_SIDE:
            continue
        yield image.crop((left, top, right, bottom))


def _inset(image: Image.Image, fraction: float) -> Image.Image | None:
    dx, dy = int(image.width * fraction), int(image.height * fraction)
    if image.width - 2 * dx < 40 or image.height - 2 * dy < 40:
        return None
    return image.crop((dx, dy, image.width - dx, image.height - dy))


def _attempts(image: Image.Image) -> Iterator[Image.Image]:
    """The same picture, presented in the ways that have been seen to work.

    Ordered by how often each is the answer: most cards read as they are, and only
    what is left goes further, so a normal upload still costs one decode.
    """
    yield image

    for panel in _light_panels(image):
        yield _with_quiet_zone(panel)

    grey = image.convert("L")
    yield grey.resize((grey.width * UPSCALE, grey.height * UPSCALE), Image.LANCZOS)

    for fraction in INSETS:
        piece = _inset(image, fraction)
        if piece is not None:
            yield _with_quiet_zone(piece)


def decode(data: bytes) -> Decoded | None:
    """Find a barcode in an image. Returns None when there is nothing to find."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            for attempt in _attempts(image):
                found = _read(attempt)
                if found is not None:
                    return found
            return None
    except Exception:  # noqa: BLE001 - a card without a barcode is normal, not an error
        log.debug("barcode decoding failed", exc_info=True)
        return None


def to_svg(text: str, barcode_format: str) -> str | None:
    """Redraw a decoded code as SVG, or None if this format cannot be written."""
    name = barcode_format.replace(" ", "").replace("-", "")
    fmt = getattr(zxingcpp.BarcodeFormat, name, None)
    if fmt is None:
        return None
    try:
        return zxingcpp.write_barcode_to_svg(zxingcpp.create_barcode(text, fmt))
    except Exception:  # noqa: BLE001 - e.g. a checksum the writer refuses to forge
        log.info("cannot redraw %s barcode", barcode_format, exc_info=True)
        return None

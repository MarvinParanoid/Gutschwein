"""Reading the barcode out of a card screenshot, and drawing it back.

At the till the app currently shows a screenshot of a screen: compressed, possibly
dim, sometimes photographed at an angle. If the code inside it can be decoded once,
at upload time, then the scan screen can draw a fresh vector barcode instead — sharp
at any zoom, and the number stays available as text if the scanner still refuses.

Decoding is deterministic: no model, no API key, no network.

A 1D barcode is only readable with a quiet zone — about ten module widths of blank
space on each side. Card apps draw the code on a coloured card, and a screenshot
cropped to that card leaves the colour right next to the bars; in greyscale it is
just another dark bar, so the decoder refuses a perfectly sharp barcode. Two of the
family's own cards failed exactly this way, and the answer was not more resolution
but less picture: take the frame off, then hand the decoder its blank margin.
"""

import io
import logging
from collections.abc import Iterator
from dataclasses import dataclass

import zxingcpp
from PIL import Image, ImageChops, ImageOps

log = logging.getLogger(__name__)

# Thin bars in a phone screenshot can fall below the decoder's resolution; the
# upscale pass recovered one of four real cards that failed at native size.
UPSCALE = 2
# The blank margin added around a cropped barcode, as a share of the shorter side.
# A barcode spanning the width of a phone screenshot has modules under 10px wide,
# so this is comfortably past the ten modules the symbologies ask for.
QUIET_ZONE = 0.05
# When the frame is not one flat colour there is nothing to trim, so a little is
# shaved off instead. Each step costs another decode, hence a short ladder — and it
# stops well before the bars: past ~10% the code itself is being cut, and half a
# code that still decodes would be a wrong number shown at the till.
INSETS = (0.03, 0.06, 0.09)
# How far a pixel may differ from the corner and still count as part of the frame.
# Screenshots are lossy, so a flat colour is never quite flat.
FRAME_TOLERANCE = 24


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
    margin = max(32, int(min(grey.width, grey.height) * QUIET_ZONE))
    return ImageOps.expand(grey, border=margin, fill=255)


def _without_frame(image: Image.Image) -> Image.Image | None:
    """The picture minus a uniform border, or None when it has none.

    The corner pixel says what the frame is made of; everything close enough to it
    is the frame. A photograph has no such border, so the box covers the whole
    image and this pass costs nothing but the comparison.
    """
    rgb = image.convert("RGB")
    flat = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    difference = ImageChops.difference(rgb, flat).convert("L")
    box = difference.point(lambda value: 255 if value > FRAME_TOLERANCE else 0).getbbox()
    if box is None or box == (0, 0, rgb.width, rgb.height):
        return None
    return rgb.crop(box)


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

    without_frame = _without_frame(image)
    if without_frame is not None:
        yield _with_quiet_zone(without_frame)

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

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

A screenshot has more than one frame, though. Penny's certificate is the dark phone
screen, then the red card, then the white panel the bars sit on, and stripping only
the outermost leaves the next one against the bars — the same forbidden neighbour.
So the frames come off one at a time, and every layer is offered to the decoder.
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
# How far a pixel may differ from a frame colour and still count as part of it.
# Screenshots are lossy, so a flat colour is never quite flat.
FRAME_TOLERANCE = 24
# How many nested frames to take off. Three is what a card screenshot actually has
# (screen, card, panel); the fourth is slack, and each one costs a decode.
FRAME_PEELS = 4
# Colours are rounded to this step before the border is polled for its most common
# one, so WebP noise does not split one flat frame into a thousand near-misses.
COLOUR_STEP = 16
# The share of each side that counts as the border ring.
BORDER_RING = 0.04
# Below this a crop cannot hold a barcode, and going further would be cutting bars.
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


def _border_colour(image: Image.Image) -> tuple[int, int, int]:
    """The most common colour around the edge — the frame, whatever shape it is.

    The corner pixel used to stand in for this, which a rounded card defeats: crop
    to the card and its corner is still the screen behind it, so the next pass finds
    nothing to strip and the ladder stops one frame short of the bars.
    """
    ring = Image.new("RGB", (image.width, max(1, int(image.height * BORDER_RING) * 2)))
    strip = max(1, int(image.height * BORDER_RING))
    ring.paste(image.crop((0, 0, image.width, strip)), (0, 0))
    ring.paste(image.crop((0, image.height - strip, image.width, image.height)), (0, strip))
    side = max(1, int(image.width * BORDER_RING))
    columns = Image.new("RGB", (side * 2, image.height))
    columns.paste(image.crop((0, 0, side, image.height)), (0, 0))
    columns.paste(image.crop((image.width - side, 0, image.width, image.height)), (side, 0))

    def round_to_step(value: int) -> int:
        return min(255, (value // COLOUR_STEP) * COLOUR_STEP + COLOUR_STEP // 2)

    counts: dict[tuple[int, int, int], int] = {}
    for part in (ring, columns):
        rounded = part.point(round_to_step)
        for count, colour in rounded.getcolors(rounded.width * rounded.height) or []:
            counts[colour] = counts.get(colour, 0) + count
    return max(counts.items(), key=lambda item: item[1])[0] if counts else (255, 255, 255)


def _content_box(
    image: Image.Image, background: tuple[tuple[int, int, int], ...]
) -> tuple[int, int, int, int] | None:
    """The box around everything that is neither the frame nor the one before it.

    The previous frame is included because a rounded card leaves its corners behind
    when it is cropped away, and a box drawn around "not the card" would grow
    straight back to them. Only the previous one, though: keep the whole history and
    a screenshot on a black screen ends up counting the bars themselves as frame,
    which is how the certificate on a black background stayed unreadable.
    """
    distance: Image.Image | None = None
    for colour in background:
        flat = Image.new("RGB", image.size, colour)
        difference = ImageChops.difference(image, flat).convert("L")
        distance = difference if distance is None else ImageChops.darker(distance, difference)
    if distance is None:
        return None
    return distance.point(lambda value: 255 if value > FRAME_TOLERANCE else 0).getbbox()


def _peeled(image: Image.Image) -> Iterator[Image.Image]:
    """The picture with one more frame taken off each time, outermost first.

    A photograph has no flat border, so the first box already covers everything and
    this costs one comparison.
    """
    rgb = image.convert("RGB")
    previous: tuple[int, int, int] | None = None
    for _ in range(FRAME_PEELS):
        colour = _border_colour(rgb)
        box = _content_box(rgb, (colour,) if previous is None else (colour, previous))
        previous = colour
        if box is None or box == (0, 0, rgb.width, rgb.height):
            return
        if box[2] - box[0] < MIN_SIDE or box[3] - box[1] < MIN_SIDE:
            return
        rgb = rgb.crop(box)
        yield rgb


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

    for stripped in _peeled(image):
        yield _with_quiet_zone(stripped)

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

"""Reading the barcode out of a card screenshot, and drawing it back.

At the till the app currently shows a screenshot of a screen: compressed, possibly
dim, sometimes photographed at an angle. If the code inside it can be decoded once,
at upload time, then the scan screen can draw a fresh vector barcode instead — sharp
at any zoom, and the number stays available as text if the scanner still refuses.

Decoding is deterministic: no model, no API key, no network.
"""

import io
import logging
from dataclasses import dataclass

import zxingcpp
from PIL import Image

log = logging.getLogger(__name__)

# Thin bars in a phone screenshot can fall below the decoder's resolution; the
# upscale pass recovered one of four real cards that failed at native size.
UPSCALE = 2


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


def decode(data: bytes) -> Decoded | None:
    """Find a barcode in an image. Returns None when there is nothing to find."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            found = _read(image)
            if found is not None:
                return found
            enlarged = image.convert("L").resize(
                (image.width * UPSCALE, image.height * UPSCALE), Image.LANCZOS
            )
            return _read(enlarged)
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

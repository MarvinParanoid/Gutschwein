"""Voucher images on disk: data/uploads/<yyyy-mm>/<random>.webp.

Everything is re-encoded to WebP on the way in. That is not primarily about disk
space — it is about what the browser can actually display: an iPhone HEIC would be
stored happily and then render as a broken image in the Mini App.

Encoding is chosen by source: screenshots (PNG-like, hard edges, few colours) are
saved losslessly, because lossy artefacts on the black-and-white edges of a barcode
are exactly what makes a scanner fail. Photographs are already lossy, so they are
re-encoded at high quality instead of being bloated into a lossless file.
"""

import asyncio
import io
import re
import secrets
import threading
from pathlib import Path

import pillow_heif
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.i18n import Message
from app.models import utcnow

pillow_heif.register_heif_opener()

# The exact shape of a name we generate. Serving, attaching and cleanup all go
# through it, so nothing else in the volume can be served, attached to a card, or
# deleted. Nothing deletes an image but the maintenance sweep. The non-webp suffixes
# are still listed: files uploaded before the conversion existed are valid.
IMAGE_ID_RE = re.compile(r"^\d{4}-\d{2}/[0-9a-f]{32}\.(webp|jpg|png|heic|heif)$")

MAX_IMAGE_BYTES = 12 * 1024 * 1024
# Long side beyond this buys nothing on a phone screen at the till, and costs
# backup space. Well above what a scanner needs off a display.
MAX_DIMENSION = 2400
WEBP_QUALITY = 90

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
# What the decoder will open, judged by the bytes, not by the declared type — which
# is the client's word. Every other Pillow plugin stays out of reach: TIFF, BMP, JPEG
# 2000 and the rest are where the decoder's memory-safety bugs have been. The JPEG
# plugin also opens MPO — the JPEG with a second frame that iPhones and many Android
# cameras save — and reports it as "MPO"; the first frame is the photo.
ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP", "HEIF")
# Formats that are lossless at the source: keep them that way.
LOSSLESS_SOURCES = {"PNG"}
# Decoded size limit, checked against the header before any pixel is decoded. 50 MP
# covers phone cameras (48 and 50 MP sensors); a screenshot is a few MP. Decoded, an
# image this size is ~150 MB, which is why decoding also runs one at a time.
MAX_PIXELS = 50_000_000
_DECODING = threading.BoundedSemaphore(1)


def _new_relative_path(suffix: str = ".webp") -> Path:
    return Path(utcnow().strftime("%Y-%m")) / f"{secrets.token_hex(16)}{suffix}"


def to_webp(data: bytes) -> bytes:
    """Decode anything we accept and re-encode as WebP. Blocking: call it in a thread."""
    try:
        with _DECODING, Image.open(io.BytesIO(data), formats=ACCEPTED_FORMATS) as image:
            if image.width * image.height > MAX_PIXELS:
                raise _too_large()
            source_format = image.format or ""
            # Phone photos carry their rotation in EXIF; re-encoding drops the tag,
            # so the pixels have to be rotated now or the card shows up sideways.
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

            lossless = source_format.upper() in LOSSLESS_SOURCES
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.mode else "RGB")

            buffer = io.BytesIO()
            # save() also drops EXIF, which quietly removes GPS from photos.
            image.save(buffer, "WEBP", lossless=lossless, quality=WEBP_QUALITY, method=4)
            return buffer.getvalue()
    except Image.DecompressionBombError as exc:
        # Pillow's own limit, for anything the header check above could not size.
        raise _too_large() from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, Message("error.image_unreadable")) from exc


def _too_large() -> HTTPException:
    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        Message("error.image_too_large", megapixels=MAX_PIXELS // 1_000_000),
    )


def save_bytes(data: bytes) -> str:
    """Store an image, converting it to WebP. Returns the relative path.

    Blocking — decoding a photo takes long enough to stall every other request.
    From async code, use `store()`.
    """
    relative = _new_relative_path()
    target = settings.upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(to_webp(data))
    return str(relative)


async def save_upload(file: UploadFile) -> str:
    if (file.content_type or "") not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            Message("error.unsupported_type", content_type=file.content_type),
        )
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            Message("error.file_too_big", limit=MAX_IMAGE_BYTES // 1024 // 1024),
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, Message("error.empty_file"))
    return await store(data)


async def store(data: bytes) -> str:
    """`save_bytes` off the event loop, refusing what is too big to be a card."""
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            Message("error.file_too_big", limit=MAX_IMAGE_BYTES // 1024 // 1024),
        )
    return await asyncio.to_thread(save_bytes, data)


def absolute_path(relative: str) -> Path:
    """Resolve a stored relative path inside upload_dir, rejecting traversal."""
    root = settings.upload_dir.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, Message("error.bad_path"))
    return target

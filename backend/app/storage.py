"""Voucher images on disk: data/uploads/<yyyy-mm>/<random>.webp.

Everything is re-encoded to WebP on the way in. That is not primarily about disk
space — it is about what the browser can actually display: an iPhone HEIC would be
stored happily and then render as a broken image in the Mini App.

Encoding is chosen by source: screenshots (PNG-like, hard edges, few colours) are
saved losslessly, because lossy artefacts on the black-and-white edges of a barcode
are exactly what makes a scanner fail. Photographs are already lossy, so they are
re-encoded at high quality instead of being bloated into a lossless file.
"""

import io
import re
import secrets
from pathlib import Path

import pillow_heif
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.models import utcnow

pillow_heif.register_heif_opener()

# The exact shape of a name we generate. Serving and cleanup both go through it,
# so nothing else in the volume can be served — or deleted. The non-webp suffixes
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
# Formats that are lossless at the source: keep them that way.
LOSSLESS_SOURCES = {"PNG", "BMP", "TIFF", "GIF"}


def _new_relative_path(suffix: str = ".webp") -> Path:
    return Path(utcnow().strftime("%Y-%m")) / f"{secrets.token_hex(16)}{suffix}"


def to_webp(data: bytes) -> bytes:
    """Decode anything we accept and re-encode as WebP."""
    try:
        with Image.open(io.BytesIO(data)) as image:
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
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Не удалось прочитать изображение"
        ) from exc


def save_bytes(data: bytes) -> str:
    """Store an image, converting it to WebP. Returns the relative path."""
    relative = _new_relative_path()
    target = settings.upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(to_webp(data))
    return str(relative)


async def save_upload(file: UploadFile) -> str:
    if (file.content_type or "") not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Неподдерживаемый тип файла: {file.content_type}",
        )
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Файл больше {MAX_IMAGE_BYTES // 1024 // 1024} МБ",
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    return save_bytes(data)


def absolute_path(relative: str) -> Path:
    """Resolve a stored relative path inside upload_dir, rejecting traversal."""
    root = settings.upload_dir.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный путь к файлу")
    return target


def delete(relative: str | None) -> None:
    if not relative:
        return
    absolute_path(relative).unlink(missing_ok=True)

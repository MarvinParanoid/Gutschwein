"""Voucher images on disk: data/uploads/<yyyy-mm>/<random>.<ext>."""

import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.models import utcnow

MAX_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def _new_relative_path(suffix: str) -> Path:
    return Path(utcnow().strftime("%Y-%m")) / f"{secrets.token_hex(16)}{suffix}"


def save_bytes(data: bytes, suffix: str = ".jpg") -> str:
    relative = _new_relative_path(suffix)
    target = settings.upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(relative)


async def save_upload(file: UploadFile) -> str:
    suffix = ALLOWED_CONTENT_TYPES.get(file.content_type or "")
    if suffix is None:
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
    return save_bytes(data, suffix)


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

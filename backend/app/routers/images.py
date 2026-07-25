"""Image delivery.

`<img src>` cannot carry an Authorization header, so images are served from
capability URLs instead: the filename is 128 bits of randomness, unguessable and
never listed. Anyone holding the link can view that one image — acceptable for a
family voucher list, and the whole point when sharing a screenshot into a chat.
"""

import re

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app import storage

router = APIRouter(prefix="/api/images", tags=["images"])

IMAGE_ID_RE = re.compile(r"^\d{4}-\d{2}/[0-9a-f]{32}\.(jpg|png|webp|heic|heif)$")


@router.get("/{image_id:path}")
async def get_image(image_id: str) -> FileResponse:
    if not IMAGE_ID_RE.match(image_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Изображение не найдено")
    path = storage.absolute_path(image_id)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Изображение не найдено")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000"})

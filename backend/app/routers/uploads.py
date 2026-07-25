from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app import storage
from app.auth import CurrentUser
from app.schemas import UploadOut

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("", response_model=UploadOut)
async def upload_image(
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> UploadOut:
    """Store an image and return the token to attach to a voucher."""
    return UploadOut(image_id=await storage.save_upload(file))

"""Redrawing a decoded barcode as SVG.

Same capability-URL rule as the images: an <img> cannot send an Authorization
header, and the address is derived from the image's own unguessable name.

The address may carry `?v=<barcode.version(code, format)>`. A versioned address
is answered only while the card still has that code, so whatever a cache keeps
under it is the barcode it claims to be: a corrected code is a new address, and
an outdated one is refused rather than answered with different bars. Without
`v` — an app from before versions — the current code is drawn, briefly cached.

SVG rather than a bitmap because the point is sharpness — the barcode stays crisp
at any zoom, and the whole thing is under a kilobyte.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import barcode, storage
from app.db import get_session
from app.i18n import Message
from app.models import Voucher

router = APIRouter(prefix="/api/barcodes", tags=["images"])


@router.get("/{image_id:path}")
async def get_barcode(
    image_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    v: str | None = None,
) -> Response:
    if not storage.IMAGE_ID_RE.match(image_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.barcode_not_found"))

    rows = await session.execute(select(Voucher).where(Voucher.image_path == image_id))
    voucher = rows.unique().scalars().first()
    if voucher is None or not voucher.code or not voucher.barcode_format:
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.barcode_not_found"))

    current = barcode.version(voucher.code, voucher.barcode_format)
    if v is not None and v != current:
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.barcode_outdated"))

    svg = barcode.to_svg(voucher.code, voucher.barcode_format)
    if svg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.barcode_not_drawable"))

    return Response(
        svg,
        media_type="image/svg+xml",
        # A checked version never changes its content; an unversioned address does
        # whenever the code is corrected, so it is kept only briefly.
        headers={
            "Cache-Control": "private, max-age=31536000, immutable"
            if v is not None
            else "private, max-age=3600"
        },
    )

"""Reading codes again out of pictures that are already stored.

The point of the command is that it may only add: a card the decoder has since
learned to read gains its code, and everything a human decided stays untouched.
"""

import io

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app import rescan
from app.db import SessionLocal
from app.models import Voucher
from tests.test_barcode import CARD_NUMBER, as_png, certificate_screenshot


def _upload(client: TestClient, image: Image.Image) -> str:
    return client.post(
        "/api/uploads",
        files={"file": ("card.png", io.BytesIO(as_png(image)), "image/png")},
    ).json()["image_id"]


async def _stored(voucher_id: int) -> Voucher:
    async with SessionLocal() as session:
        rows = await session.execute(select(Voucher).where(Voucher.id == voucher_id))
        return rows.unique().scalars().one()


async def test_a_picture_that_only_decodes_now_gets_its_code(client: TestClient) -> None:
    image_id = _upload(client, certificate_screenshot())
    voucher = client.post("/api/vouchers", json={"merchant": "Penny", "image_id": image_id}).json()

    # Back to how the row looked before the decoder could read this picture.
    async with SessionLocal() as session:
        stored = await session.get(Voucher, voucher["id"])
        assert stored is not None
        stored.code = ""
        stored.barcode_format = None
        await session.commit()

    await rescan.rescan(apply=True, everything=False)

    after = await _stored(voucher["id"])
    assert after.code == CARD_NUMBER
    assert after.barcode_format == "Code 128"


async def test_a_typed_code_survives_the_rescan(client: TestClient) -> None:
    image_id = _upload(client, certificate_screenshot())
    voucher = client.post(
        "/api/vouchers",
        json={"merchant": "Penny", "code": "ВПИСАНО РУКАМИ", "image_id": image_id},
    ).json()

    async with SessionLocal() as session:
        stored = await session.get(Voucher, voucher["id"])
        assert stored is not None
        stored.barcode_format = None
        await session.commit()

    await rescan.rescan(apply=True, everything=True)

    after = await _stored(voucher["id"])
    assert after.code == "ВПИСАНО РУКАМИ"


async def test_without_apply_nothing_is_written(client: TestClient) -> None:
    image_id = _upload(client, certificate_screenshot())
    voucher = client.post("/api/vouchers", json={"merchant": "Penny", "image_id": image_id}).json()

    async with SessionLocal() as session:
        stored = await session.get(Voucher, voucher["id"])
        assert stored is not None
        stored.code = ""
        stored.barcode_format = None
        await session.commit()

    await rescan.rescan(apply=False, everything=False)

    after = await _stored(voucher["id"])
    assert after.code == ""
    assert after.barcode_format is None


async def test_an_unreadable_picture_keeps_what_it_had(client: TestClient) -> None:
    """A rescan that finds nothing must not clear a format found earlier."""
    blank = Image.new("RGB", (600, 400), "white")
    image_id = _upload(client, blank)
    voucher = client.post(
        "/api/vouchers", json={"merchant": "Без кода", "image_id": image_id}
    ).json()

    async with SessionLocal() as session:
        stored = await session.get(Voucher, voucher["id"])
        assert stored is not None
        stored.barcode_format = "Code 128"
        stored.code = "OLD-1"
        await session.commit()

    await rescan.rescan(apply=True, everything=True)

    after = await _stored(voucher["id"])
    assert after.barcode_format == "Code 128"
    assert after.code == "OLD-1"


async def test_a_pair_that_cannot_draw_is_repaired_only_when_asked(client: TestClient) -> None:
    """How an older version left a replaced picture: the new format, the old code.

    Nothing can draw that, and it is what turned a card into a broken picture at the
    till. `--repair` says so out loud rather than assuming the code was the picture's:
    a code someone typed is still nobody else's to overwrite.
    """
    image_id = _upload(client, certificate_screenshot())
    voucher = client.post(
        "/api/vouchers", json={"merchant": "Verdreht", "image_id": image_id}
    ).json()

    async with SessionLocal() as session:
        stored = await session.get(Voucher, voucher["id"])
        assert stored is not None
        stored.code = "https://coupons.example/x"  # the discarded picture's code
        stored.barcode_format = "EAN-13"  # the new picture's format
        await session.commit()

    await rescan.rescan(apply=True, everything=True)
    untouched = await _stored(voucher["id"])
    assert (untouched.code, untouched.barcode_format) == ("https://coupons.example/x", "EAN-13")

    await rescan.rescan(apply=True, everything=True, repair=True)
    repaired = await _stored(voucher["id"])
    assert (repaired.code, repaired.barcode_format) == (CARD_NUMBER, "Code 128")


async def test_a_pair_that_draws_is_left_alone_even_when_asked(client: TestClient) -> None:
    """The bars an EAN-13 card shows are that card's business, not the picture's."""
    image_id = _upload(client, certificate_screenshot())
    voucher = client.post("/api/vouchers", json={"merchant": "Eigene", "image_id": image_id}).json()

    async with SessionLocal() as session:
        stored = await session.get(Voucher, voucher["id"])
        assert stored is not None
        stored.code = "5000000000005"
        stored.barcode_format = "EAN-13"
        await session.commit()

    await rescan.rescan(apply=True, everything=True, repair=True)

    after = await _stored(voucher["id"])
    assert (after.code, after.barcode_format) == ("5000000000005", "EAN-13")

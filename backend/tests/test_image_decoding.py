"""What the image decoder will open, and what it costs (T1, T8).

Pillow probes every plugin it has, whatever the upload claims to be: a TIFF sent as
`image/png` used to be decoded — and TIFF, BMP and JPEG 2000 are where Pillow's
memory-safety bugs have been. A decompression bomb was an unhandled 500, and every
decode ran on the event loop, stalling every other request while it worked.
"""

import asyncio
import io
import threading
import time
from collections.abc import AsyncIterator

import httpx
import pillow_heif
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import barcode, storage
from app.config import settings
from app.main import app

H = {"X-Dev-User": "1000"}


def _encode(fmt: str, size=(64, 48), mode="RGB", **kw) -> bytes:
    buffer = io.BytesIO()
    image = Image.new(mode, size, "white" if mode != "1" else 1)
    if fmt == "MPO":
        image.save(buffer, "MPO", save_all=True, append_images=[image.copy()])
    else:
        image.save(buffer, fmt, **kw)
    return buffer.getvalue()


@pytest.fixture
async def api(client: TestClient) -> AsyncIterator[httpx.AsyncClient]:
    """`client` is here for its side effect: it runs the migrations."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        yield http


async def _upload(api, data: bytes, content_type: str = "image/png", name: str = "x.png"):
    return await api.post("/api/uploads", headers=H, files={"file": (name, data, content_type)})


def _stored(response: httpx.Response) -> Image.Image:
    return Image.open(settings.upload_dir / response.json()["image_id"])


# --- the formats a card is made of --------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "content_type"),
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("WEBP", "image/webp"),
        ("HEIF", "image/heic"),
        ("MPO", "image/jpeg"),  # what iPhones and many Android cameras actually save
    ],
)
async def test_the_formats_phones_produce_are_accepted(api, fmt, content_type) -> None:
    if fmt == "HEIF":
        pillow_heif.register_heif_opener()
    response = await _upload(api, _encode(fmt), content_type)

    assert response.status_code == 200, response.text
    stored = _stored(response)
    assert (stored.format, stored.size) == ("WEBP", (64, 48))


async def test_a_screenshot_stays_lossless_and_a_photo_does_not(api) -> None:
    """Unchanged behaviour: barcode edges in a PNG must survive re-encoding exactly."""
    pattern = Image.new("RGB", (64, 48), "white")
    for x in range(0, 64, 2):
        for y in range(48):
            pattern.putpixel((x, y), (0, 0, 0))
    buffer = io.BytesIO()
    pattern.save(buffer, "PNG")

    response = await _upload(api, buffer.getvalue())

    assert _stored(response).convert("RGB").tobytes() == pattern.tobytes()


@pytest.mark.parametrize(
    ("fmt", "kw"),
    [("TIFF", {}), ("BMP", {}), ("GIF", {}), ("JPEG2000", {}), ("ICO", {}), ("PPM", {})],
)
@pytest.mark.parametrize("declared", ["image/png", "image/jpeg"])
async def test_other_formats_are_refused_whatever_they_claim_to_be(api, fmt, kw, declared) -> None:
    response = await _upload(api, _encode(fmt, **kw), declared)

    assert response.status_code == 400
    assert response.json()["detail"] == "Не удалось прочитать изображение"


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,  # a PNG signature and nothing after it
        _encode("PNG")[:40],  # truncated mid-header
        _encode("JPEG")[:-200],  # truncated mid-image
        b"GIF89a" + b"\x00" * 20,
        b"not an image at all",
    ],
)
async def test_malformed_files_are_a_400_not_a_500(api, data) -> None:
    response = await _upload(api, data, "image/jpeg")

    assert response.status_code == 400


# --- size -------------------------------------------------------------------------------


async def test_too_many_pixels_is_refused_before_decoding(api, monkeypatch) -> None:
    """56 MP of white compresses to a few kilobytes — the size is in the header."""
    data = _encode("PNG", size=(8000, 7000), mode="1")
    assert len(data) < 100_000
    decoded = []
    real_load = Image.Image.load
    monkeypatch.setattr(Image.Image, "load", lambda self: decoded.append(1) or real_load(self))

    response = await _upload(api, data)

    assert response.status_code == 400
    assert "50" in response.json()["detail"] and "мегапиксел" in response.json()["detail"]
    assert decoded == []  # refused from the header, no pixel decoded


async def test_a_decompression_bomb_is_a_400(api) -> None:
    response = await _upload(api, _encode("PNG", size=(20000, 20000), mode="1"))

    assert response.status_code == 400


async def test_more_bytes_than_the_limit_is_a_413(api) -> None:
    data = _encode("PNG") + b"\x00" * (storage.MAX_IMAGE_BYTES + 1)

    response = await _upload(api, data)

    assert response.status_code == 413


async def test_a_photo_at_the_limit_of_a_phone_camera_is_accepted(api) -> None:
    """48 MP — a current phone's full resolution — is a card, not an attack."""
    response = await _upload(api, _encode("JPEG", size=(8000, 6000)), "image/jpeg")

    assert response.status_code == 200
    assert max(_stored(response).size) == storage.MAX_DIMENSION


# --- the event loop -----------------------------------------------------------------------


async def test_decoding_runs_off_the_event_loop_one_at_a_time(api, monkeypatch) -> None:
    loop_thread = threading.get_ident()
    threads, running, peak = [], [0], [0]
    real = storage.to_webp

    def slow(data: bytes) -> bytes:
        threads.append(threading.get_ident())
        with storage._DECODING:  # what to_webp holds; measured from inside it
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            time.sleep(0.2)
            running[0] -= 1
        return real(data)

    monkeypatch.setattr(storage, "to_webp", slow)
    # While two uploads decode, the loop keeps answering.
    ticks = []

    async def heartbeat():
        for _ in range(10):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.03)

    results = await asyncio.gather(
        _upload(api, _encode("PNG")), _upload(api, _encode("PNG")), heartbeat()
    )

    assert [r.status_code for r in results[:2]] == [200, 200]
    assert loop_thread not in threads
    assert peak[0] == 1
    assert len(ticks) == 10 and ticks[-1] - ticks[0] < 1.0


# --- stored pictures ------------------------------------------------------------------------


def test_the_barcode_reader_applies_the_same_gate() -> None:
    assert barcode.decode(_encode("TIFF")) is None
    assert barcode.decode(_encode("PNG", size=(8000, 7000), mode="1")) is None

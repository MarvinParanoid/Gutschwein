"""Image intake: everything becomes WebP, and a barcode must survive the trip."""

import io

import pillow_heif
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import storage
from app.config import settings

pillow_heif.register_heif_opener()


def barcode_image(width: int = 400, height: int = 200) -> Image.Image:
    """Hard black-and-white edges — the thing lossy compression ruins."""
    image = Image.new("RGB", (width, height), "white")
    for x in range(0, width, 7):
        for y in range(height):
            for dx in range(3):
                if x + dx < width:
                    image.putpixel((x + dx, y), (0, 0, 0))
    return image


def encode(image: Image.Image, fmt: str, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def upload(client: TestClient, data: bytes, name: str, content_type: str):
    return client.post("/api/uploads", files={"file": (name, io.BytesIO(data), content_type)})


def stored(image_id: str) -> Image.Image:
    return Image.open(settings.upload_dir / image_id)


def test_png_screenshot_is_stored_lossless(client: TestClient) -> None:
    source = barcode_image()
    response = upload(client, encode(source, "PNG"), "shot.png", "image/png")
    assert response.status_code == 200

    image_id = response.json()["image_id"]
    assert image_id.endswith(".webp")

    saved = stored(image_id)
    assert saved.format == "WEBP"
    # Pixel-identical: a scanner sees exactly what was uploaded.
    assert saved.convert("RGB").tobytes() == source.tobytes()


def test_jpeg_photo_is_converted(client: TestClient) -> None:
    source = barcode_image(600, 400)
    response = upload(client, encode(source, "JPEG", quality=92), "photo.jpg", "image/jpeg")
    image_id = response.json()["image_id"]

    saved = stored(image_id)
    assert saved.format == "WEBP"
    assert saved.size == (600, 400)


def test_heic_from_an_iphone_becomes_displayable(client: TestClient) -> None:
    """HEIC used to be stored as-is and then failed to render in the webview."""
    heic = encode(barcode_image(300, 300), "HEIF")
    response = upload(client, heic, "IMG_0001.heic", "image/heic")
    assert response.status_code == 200

    image_id = response.json()["image_id"]
    assert image_id.endswith(".webp")
    assert stored(image_id).format == "WEBP"

    # And the browser can actually fetch it.
    with TestClient(client.app) as anon:
        served = anon.get(f"/api/images/{image_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"


def test_exif_rotation_is_baked_in(client: TestClient) -> None:
    """Re-encoding drops EXIF, so the rotation has to be applied to the pixels."""
    portrait = barcode_image(200, 400)
    exif = Image.Exif()
    exif[274] = 6  # Orientation: rotate 90° clockwise
    data = encode(portrait, "JPEG", exif=exif)

    image_id = upload(client, data, "rotated.jpg", "image/jpeg").json()["image_id"]
    # 200x400 tagged "rotate" must come out as 400x200, not sideways in the app.
    assert stored(image_id).size == (400, 200)


def test_huge_photo_is_downscaled(client: TestClient) -> None:
    huge = barcode_image(4000, 3000)
    image_id = upload(client, encode(huge, "JPEG"), "big.jpg", "image/jpeg").json()["image_id"]

    saved = stored(image_id)
    assert max(saved.size) == storage.MAX_DIMENSION
    # Aspect ratio preserved.
    assert saved.size == (2400, 1800)


def test_broken_file_is_rejected_with_a_clear_error(client: TestClient) -> None:
    response = upload(client, b"not really a png", "fake.png", "image/png")
    assert response.status_code == 400
    assert "прочитать" in response.json()["detail"]


def test_unsupported_type_still_refused(client: TestClient) -> None:
    assert upload(client, b"%PDF-1.4", "card.pdf", "application/pdf").status_code == 415


@pytest.mark.parametrize(
    "name",
    [
        "2026-07/" + "a" * 32 + ".webp",
        # Files uploaded before conversion existed must stay servable.
        "2026-07/" + "a" * 32 + ".png",
        "2026-07/" + "a" * 32 + ".jpg",
    ],
)
def test_legacy_names_remain_valid(name: str) -> None:
    assert storage.IMAGE_ID_RE.match(name)

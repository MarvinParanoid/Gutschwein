"""Orphan image cleanup — the risky part is what it must NOT delete."""

import io
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.maintenance import cleanup_orphan_images

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def _age(path: Path, hours: float) -> None:
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


async def test_deletes_only_stale_unreferenced_images(client: TestClient) -> None:
    upload = client.post("/api/uploads", files={"file": ("a.png", io.BytesIO(PNG), "image/png")})
    attached_id = upload.json()["image_id"]
    client.post(
        "/api/vouchers",
        json={"merchant": "Keeper", "value_kind": "amount", "value_amount": "10",
              "image_id": attached_id},
    )
    attached = settings.upload_dir / attached_id

    orphan_old = settings.upload_dir / "2026-07" / f"{'a' * 32}.png"
    orphan_old.parent.mkdir(parents=True, exist_ok=True)
    orphan_old.write_bytes(PNG)
    _age(orphan_old, 48)

    # Uploaded a minute ago: a form may still be open with it.
    orphan_fresh = settings.upload_dir / "2026-07" / f"{'b' * 32}.png"
    orphan_fresh.write_bytes(PNG)

    # Not ours: wrong name shape. Must survive regardless of age.
    foreign = settings.upload_dir / "2026-07" / "important-notes.txt"
    foreign.write_bytes(b"do not delete me")
    _age(foreign, 500)

    # An old file that IS referenced must survive too.
    _age(attached, 500)

    async with SessionLocal() as session:
        removed, freed = await cleanup_orphan_images(session)

    assert removed == 1
    assert freed == len(PNG)
    assert not orphan_old.exists()
    assert orphan_fresh.exists()
    assert foreign.exists()
    assert attached.exists()


async def test_grace_period_is_configurable(client: TestClient) -> None:
    fresh_orphan = settings.upload_dir / "2026-07" / f"{'c' * 32}.png"
    fresh_orphan.parent.mkdir(parents=True, exist_ok=True)
    fresh_orphan.write_bytes(PNG)

    async with SessionLocal() as session:
        removed, _ = await cleanup_orphan_images(session, grace_seconds=0)

    assert removed >= 1
    assert not fresh_orphan.exists()


async def test_empty_month_directories_are_removed(client: TestClient) -> None:
    empty = settings.upload_dir / "2019-01"
    empty.mkdir(parents=True, exist_ok=True)

    async with SessionLocal() as session:
        await cleanup_orphan_images(session)

    assert not empty.exists()

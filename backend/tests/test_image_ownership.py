"""A stored picture belongs to one card, and only the sweep ever deletes it (F6).

Two cards could point at one file, and deleting either deleted the picture of the
other. Replacing a picture deleted the old file before the commit, so a failed
commit left the card pointing at nothing. Now a picture is claimed by one card
under the writer lock, request handlers delete nothing, and the maintenance sweep
removes a file only after checking, under the same lock, that nothing claims it.
"""

import asyncio
import io
import os
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app import maintenance
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.maintenance import cleanup_orphan_images
from app.models import Event, EventKind, Voucher
from app.routers import vouchers as vouchers_router

ANNA = {"X-Dev-User": "1000"}


@pytest.fixture
async def api(client: TestClient) -> AsyncIterator[httpx.AsyncClient]:
    """`client` is here for its side effect: it runs the migrations."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        assert (await http.get("/api/me", headers=ANNA)).status_code == 200
        yield http


async def _upload(api: httpx.AsyncClient) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    response = await api.post(
        "/api/uploads", headers=ANNA, files={"file": ("c.png", buffer.getvalue(), "image/png")}
    )
    assert response.status_code == 200
    return response.json()["image_id"]


def _file(image_id: str):
    return settings.upload_dir / image_id


def _age(image_id: str) -> None:
    """Make a file look older than the sweep's grace period."""
    old = time.time() - maintenance.GRACE_SECONDS - 3600
    os.utime(_file(image_id), (old, old))


async def _create(api: httpx.AsyncClient, merchant: str, image_id: str | None):
    return await api.post(
        "/api/vouchers", headers=ANNA, json={"merchant": merchant, "image_id": image_id}
    )


async def _card(api: httpx.AsyncClient, merchant: str, image_id: str | None = None) -> dict:
    response = await _create(api, merchant, image_id)
    assert response.status_code == 201
    return response.json()


async def _count(merchant: str) -> int:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(Voucher).where(Voucher.merchant == merchant)
            )
        ).scalar_one()


async def _events(card_id: int) -> list[str]:
    async with SessionLocal() as db:
        rows = await db.execute(
            select(Event.kind).where(Event.voucher_id == card_id).order_by(Event.id)
        )
        return list(rows.scalars().all())


async def _sweep() -> int:
    async with SessionLocal() as db:
        removed, _freed = await cleanup_orphan_images(db)
        return removed


# --- attaching -----------------------------------------------------------------


async def test_a_picture_cannot_be_attached_to_a_second_card(api) -> None:
    image = await _upload(api)
    owner = await _card(api, "Own-First", image)

    refused = await _create(api, "Own-Second", image)

    assert refused.status_code == 409
    assert await _count("Own-Second") == 0
    assert (await api.get(f"/api/vouchers/{owner['id']}", headers=ANNA)).json()["image_id"] == image


async def test_patching_in_another_cards_picture_is_refused(api) -> None:
    image = await _upload(api)
    await _card(api, "Own-Holder", image)
    other = await _card(api, "Own-Taker", await _upload(api))
    before = await _events(other["id"])

    refused = await api.patch(
        f"/api/vouchers/{other['id']}", headers=ANNA, json={"image_id": image, "notes": "x"}
    )

    assert refused.status_code == 409
    after = (await api.get(f"/api/vouchers/{other['id']}", headers=ANNA)).json()
    assert (after["image_id"], after["notes"]) == (other["image_id"], "")
    assert await _events(other["id"]) == before


async def test_a_card_keeps_its_own_picture_on_every_save(api) -> None:
    image = await _upload(api)
    card = await _card(api, "Own-Keeps", image)

    saved = await api.patch(
        f"/api/vouchers/{card['id']}", headers=ANNA, json={"image_id": image, "notes": "again"}
    )

    assert saved.status_code == 200
    assert saved.json()["image_id"] == image
    assert EventKind.image_replaced not in await _events(card["id"])


async def test_a_card_whose_picture_predates_the_rules_stays_editable(api) -> None:
    """A stored reference the attach check would refuse today is still the card's own."""
    card = await _card(api, "Own-Legacy")
    async with SessionLocal() as db:
        await db.execute(
            update(Voucher).where(Voucher.id == card["id"]).values(image_path="legacy.png")
        )
        await db.commit()

    saved = await api.patch(
        f"/api/vouchers/{card['id']}", headers=ANNA, json={"image_id": "legacy.png", "notes": "x"}
    )

    assert saved.status_code == 200


@pytest.mark.parametrize("bad", ["notes.txt", "2026-10", "../test.db", f"2026-10/{'d' * 32}.webp"])
async def test_only_existing_pictures_with_a_generated_name_attach(api, bad) -> None:
    (settings.upload_dir / "notes.txt").write_text("not a picture")
    (settings.upload_dir / "2026-10").mkdir(exist_ok=True)
    card = await _card(api, f"Own-Bad-{bad[:4]}")

    assert (await _create(api, "Own-Bad-New", bad)).status_code == 400
    patched = await api.patch(f"/api/vouchers/{card['id']}", headers=ANNA, json={"image_id": bad})
    assert patched.status_code == 400
    assert await _count("Own-Bad-New") == 0


# --- nothing is deleted by a request --------------------------------------------


async def test_deleting_a_card_leaves_its_picture_for_the_sweep(api) -> None:
    image = await _upload(api)
    card = await _card(api, "Del-Card", image)

    assert (await api.delete(f"/api/vouchers/{card['id']}", headers=ANNA)).status_code == 204
    assert _file(image).is_file()

    _age(image)
    assert await _sweep() >= 1
    assert not _file(image).exists()


async def test_replacing_a_picture_leaves_the_old_one_for_the_sweep(api) -> None:
    old, new = await _upload(api), await _upload(api)
    card = await _card(api, "Replace-Card", old)

    replaced = await api.patch(f"/api/vouchers/{card['id']}", headers=ANNA, json={"image_id": new})
    assert replaced.json()["image_id"] == new
    assert _file(old).is_file()

    _age(old)
    _age(new)
    await _sweep()
    assert not _file(old).exists()
    assert _file(new).is_file()  # referenced, however old


@pytest.mark.parametrize("replacement", ["new", None], ids=["replace", "remove"])
async def test_a_failed_commit_keeps_the_pictures(api, monkeypatch, replacement) -> None:
    old = await _upload(api)
    new = await _upload(api) if replacement else None
    card = await _card(api, f"Fail-{replacement}", old)
    real = vouchers_router.record_event

    def broken(session, voucher, actor, kind, payload=None):
        event = real(session, voucher, actor, kind, payload)
        if kind == EventKind.image_replaced:
            event.kind = None  # NOT NULL: the commit fails
        return event

    monkeypatch.setattr(vouchers_router, "record_event", broken)
    with pytest.raises(IntegrityError):
        await api.patch(f"/api/vouchers/{card['id']}", headers=ANNA, json={"image_id": new})

    assert (await api.get(f"/api/vouchers/{card['id']}", headers=ANNA)).json()["image_id"] == old
    assert (await api.get(f"/api/images/{old}")).status_code == 200
    if new:
        assert _file(new).is_file()


async def test_the_database_refuses_a_second_owner_too(api) -> None:
    """Migration 0011: a duplicate written past the app is refused by SQLite itself."""
    image = await _upload(api)
    await _card(api, "Unique-First", image)
    second = await _card(api, "Unique-Second")

    async with SessionLocal() as db:
        with pytest.raises(IntegrityError, match="image_path"):
            await db.execute(
                update(Voucher).where(Voucher.id == second["id"]).values(image_path=image)
            )


async def test_cards_without_a_picture_do_not_collide(api) -> None:
    for n in range(3):
        await _card(api, f"Unique-None-{n}")
    async with SessionLocal() as db:
        nulls = await db.execute(
            select(func.count())
            .select_from(Voucher)
            .where(Voucher.merchant.like("Unique-None-%"), Voucher.image_path.is_(None))
        )
        assert nulls.scalar_one() == 3


@pytest.mark.parametrize("how", ["create", "patch"])
async def test_the_databases_refusal_is_a_409_not_a_500(api, monkeypatch, how) -> None:
    """With the app's own check out of the way, the index answers — still as a 409."""
    image = await _upload(api)
    await _card(api, f"Unique-Owner-{how}", image)

    async def no_check(session, image_id, voucher_id):
        return None

    monkeypatch.setattr(vouchers_router, "_claim_image", no_check)
    if how == "create":
        response = await _create(api, "Unique-Bypass", image)
        assert await _count("Unique-Bypass") == 0
    else:
        other = await _card(api, "Unique-Bypass-Patch")
        response = await api.patch(
            f"/api/vouchers/{other['id']}", headers=ANNA, json={"image_id": image}
        )
        assert await _events(other["id"]) == [EventKind.created]

    assert response.status_code == 409
    assert response.json()["detail"]


# --- concurrency -------------------------------------------------------------------


def _pause_both_before_the_lock(monkeypatch, barrier: asyncio.Barrier) -> None:
    """Both requests pass their early checks before either takes the lock: the
    worst case for an ownership check that is not serialised."""
    attach, read = vouchers_router.attach_barcode, vouchers_router.read_barcode

    async def attach_then_wait(voucher):
        await attach(voucher)
        await asyncio.wait_for(barrier.wait(), 5)

    async def read_then_wait(image_path):
        found = await read(image_path)
        await asyncio.wait_for(barrier.wait(), 5)
        return found

    monkeypatch.setattr(vouchers_router, "attach_barcode", attach_then_wait)
    monkeypatch.setattr(vouchers_router, "read_barcode", read_then_wait)


async def test_two_cards_created_at_once_with_one_picture(api, monkeypatch) -> None:
    image = await _upload(api)
    _pause_both_before_the_lock(monkeypatch, asyncio.Barrier(2))

    responses = await asyncio.gather(_create(api, "Race-CC", image), _create(api, "Race-CC", image))

    assert sorted(r.status_code for r in responses) == [201, 409]
    assert await _count("Race-CC") == 1
    winner = next(r for r in responses if r.status_code == 201).json()
    assert await _events(winner["id"]) == [EventKind.created]


async def test_a_create_and_a_patch_at_once_with_one_picture(api, monkeypatch) -> None:
    image = await _upload(api)
    existing = await _card(api, "Race-CP-Existing", await _upload(api))
    _pause_both_before_the_lock(monkeypatch, asyncio.Barrier(2))

    created, patched = await asyncio.gather(
        _create(api, "Race-CP-New", image),
        api.patch(f"/api/vouchers/{existing['id']}", headers=ANNA, json={"image_id": image}),
    )

    assert sorted([created.status_code, patched.status_code]) in ([200, 409], [201, 409])
    async with SessionLocal() as db:
        owners = await db.execute(select(Voucher.id).where(Voucher.image_path == image))
        assert len(owners.all()) == 1


async def test_the_sweep_spares_a_picture_attached_while_it_was_scanning(api, monkeypatch) -> None:
    """The sweep has picked an old orphan; before it locks, a card claims it."""
    image = await _upload(api)
    _age(image)
    reached, release = asyncio.Event(), asyncio.Event()
    real = maintenance.take_writer_lock

    async def wait_then_lock(session):
        reached.set()
        await release.wait()
        await real(session)

    monkeypatch.setattr(maintenance, "take_writer_lock", wait_then_lock)
    sweep = asyncio.create_task(_sweep())
    await asyncio.wait_for(reached.wait(), 5)
    card = await _card(api, "Sweep-Claimed", image)
    release.set()
    await sweep

    assert _file(image).is_file()
    assert (await api.get(f"/api/vouchers/{card['id']}", headers=ANNA)).json()["image_id"] == image


async def test_a_picture_the_sweep_deletes_cannot_be_attached_after_all(api, monkeypatch) -> None:
    """The sweep holds the lock when a card tries to claim the file it is deleting:
    the card waits, then finds the file gone and is refused — never left pointing
    at nothing."""
    image = await _upload(api)
    _age(image)
    locked, release = asyncio.Event(), asyncio.Event()
    real = maintenance.take_writer_lock

    async def lock_then_hold(session):
        await real(session)
        if not locked.is_set():
            locked.set()
            await release.wait()

    monkeypatch.setattr(maintenance, "take_writer_lock", lock_then_hold)
    sweep = asyncio.create_task(_sweep())
    await asyncio.wait_for(locked.wait(), 5)
    attempt = asyncio.create_task(_create(api, "Sweep-Lost", image))
    await asyncio.sleep(0.2)  # let it pass its early check and queue on the lock
    assert not attempt.done()
    release.set()
    await sweep

    assert (await attempt).status_code == 400
    assert not _file(image).exists()
    assert await _count("Sweep-Lost") == 0

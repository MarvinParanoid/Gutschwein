"""Backup archive building. Sending needs a real bot, so that part is not covered."""

import sqlite3
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import backup
from app.config import settings


def test_archive_contains_database_and_images(client: TestClient, tmp_path: Path) -> None:
    # Something in the database and at least one uploaded image.
    client.post(
        "/api/vouchers",
        json={"merchant": "Backup-Shop", "value_kind": "amount", "value_amount": "10"},
    )
    (settings.upload_dir / "2026-07").mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "2026-07" / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png").write_bytes(b"x")

    archive, summary = backup.create_archive(tmp_path)

    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "sparschwein.db" in names
    assert any(n.startswith("uploads/") for n in names)
    assert "МБ" in summary


def test_snapshot_is_a_readable_database(client: TestClient, tmp_path: Path) -> None:
    """A plain copy of a live SQLite file can be torn; the snapshot must not be."""
    client.get("/api/vouchers")  # make sure the database exists and has been written to
    archive, _ = backup.create_archive(tmp_path)

    with tarfile.open(archive) as tar:
        tar.extract("sparschwein.db", path=tmp_path, filter="data")

    with sqlite3.connect(tmp_path / "sparschwein.db") as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"vouchers", "events", "comments", "users"} <= tables


def test_oversized_archive_drops_images(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    big = settings.upload_dir / "2026-07" / "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"
    big.parent.mkdir(parents=True, exist_ok=True)
    # Incompressible bytes, so gzip cannot hide them under the limit.
    big.write_bytes(__import__("os").urandom(200_000))
    monkeypatch.setattr(backup, "MAX_UPLOAD_BYTES", 50_000)

    archive, summary = backup.create_archive(tmp_path)

    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert names == ["sparschwein.db"]
    assert "Картинки не влезли" in summary


def test_database_file_resolved_from_url() -> None:
    assert backup.database_file() is not None
    assert backup.database_file().name.endswith(".db")

"""The rename must not look like data loss to anyone who already runs the app."""

from pathlib import Path

from app.config import settings
from app.migrations import LEGACY_DB_NAME, adopt_legacy_database


def _point_at(monkeypatch, directory: Path) -> Path:
    current = directory / "gutschwein.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{current}")
    return current


def test_the_old_file_is_taken_over(monkeypatch, tmp_path: Path) -> None:
    current = _point_at(monkeypatch, tmp_path)
    legacy = tmp_path / LEGACY_DB_NAME
    legacy.write_bytes(b"the family's cards")
    (tmp_path / f"{LEGACY_DB_NAME}-wal").write_bytes(b"not checkpointed yet")

    adopt_legacy_database()

    assert current.read_bytes() == b"the family's cards"
    assert Path(f"{current}-wal").read_bytes() == b"not checkpointed yet"
    assert not legacy.exists()


def test_an_existing_database_is_never_overwritten(monkeypatch, tmp_path: Path) -> None:
    current = _point_at(monkeypatch, tmp_path)
    current.write_bytes(b"current")
    (tmp_path / LEGACY_DB_NAME).write_bytes(b"stale leftover")

    adopt_legacy_database()

    assert current.read_bytes() == b"current"


def test_a_fresh_install_is_left_alone(monkeypatch, tmp_path: Path) -> None:
    current = _point_at(monkeypatch, tmp_path)
    adopt_legacy_database()
    assert not current.exists()

"""Run Alembic migrations from inside the app process.

Called via asyncio.to_thread at startup: Alembic is synchronous, so it needs a
thread of its own rather than the running event loop.
"""

import logging
from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.config import settings

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parent.parent
# The project used to be called Sparschwein. Drop this once no install is that old.
LEGACY_DB_NAME = "sparschwein.db"


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def adopt_legacy_database() -> None:
    """Take over the database left by the project's previous name.

    Renaming the app renamed the file it looks for. Without this an existing
    install would start, find nothing, create an empty database beside the real
    one, and greet the family with an app that has lost all their cards — while
    the data sits untouched under the old name.
    """
    url = make_url(settings.database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return
    current = Path(url.database)
    legacy = current.with_name(LEGACY_DB_NAME)
    if current.exists() or not legacy.exists():
        return

    # -wal and -shm belong to the same database; leaving them behind would
    # discard whatever had not been checkpointed yet.
    for suffix in ("", "-wal", "-shm"):
        source = legacy.with_name(legacy.name + suffix)
        if source.exists():
            source.rename(current.with_name(current.name + suffix))
    log.info("adopted the database left under the old name %s", legacy.name)


def upgrade_database() -> None:
    adopt_legacy_database()
    log.info("running database migrations")
    command.upgrade(alembic_config(), "head")

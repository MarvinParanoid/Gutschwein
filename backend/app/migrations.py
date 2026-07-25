"""Run Alembic migrations from inside the app process.

Called via asyncio.to_thread at startup: Alembic is synchronous, so it needs a
thread of its own rather than the running event loop.
"""

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def upgrade_database() -> None:
    log.info("running database migrations")
    command.upgrade(alembic_config(), "head")

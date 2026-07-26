"""Test environment.

Settings are read once at import time, so the environment must be prepared
before anything from `app` is imported.
"""

import os
import tempfile
from collections.abc import Iterator

import pytest

TMP_DIR = tempfile.mkdtemp(prefix="gutschwein-tests-")
os.environ.update(
    DEV_MODE="true",
    RUN_BOT="false",
    BOT_TOKEN="",
    ALLOWED_TELEGRAM_IDS="",
    DATA_DIR=TMP_DIR,
    DATABASE_URL=f"sqlite+aiosqlite:///{TMP_DIR}/test.db",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    # https, because the session cookie is Secure and a client will not send it
    # over plain http — same as a real browser.
    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.headers["X-Dev-User"] = "1000"
        yield test_client


@pytest.fixture
def other_client(client: TestClient) -> Iterator[TestClient]:
    """A second family member, to check cross-user visibility."""
    with TestClient(app) as second:
        second.headers["X-Dev-User"] = "2000"
        yield second

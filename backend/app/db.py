"""The database engine, and the three PRAGMAs SQLite does not set by itself.

SQLite's defaults are the ones a command-line tool wants, not the ones a server
does, and they are per connection — so they are applied every time one is opened.

  * `foreign_keys`. Off by default, which makes every `ON DELETE CASCADE` in
    models.py decoration and every foreign key unenforced. Deleting a member used
    to succeed and leave their vouchers pointing at a row that no longer exists;
    SQLite then reuses the id, and the next member created inherits their history —
    a card silently changes author. With this on, deleting a member who has history
    is refused instead, which is the right answer.
  * `journal_mode=WAL`. Under the default, a writer blocks every reader for the
    length of its transaction, and this app writes on paths that look like reads.
  * `busy_timeout`. Present by default through the driver, set here so it is stated
    rather than inherited.
"""

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

BUSY_TIMEOUT_MS = 5000

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


async def take_writer_lock(session: AsyncSession) -> None:
    """Start a write transaction now, holding SQLite's single writer lock to commit.

    For work that has to be serialised with writers but has no row of its own to
    lock (`services.lock_voucher_or_404` is the version for one voucher). An UPDATE
    that matches nothing still opens the write transaction — pysqlite emits BEGIN
    before any DML, and SQLite takes the lock when the statement starts, not when
    a row changes. Keep what follows short: every other writer waits on it.
    """
    await session.execute(text("UPDATE vouchers SET id = id WHERE 0"))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

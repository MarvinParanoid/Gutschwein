"""Logging in outside Telegram.

Inside Telegram the identity comes for free: `initData` is signed by the bot token
and verified on every request. A browser has none of that, so a PWA needs a session
of its own — the only credential this app issues.

The flow keeps the trust in Telegram: the bot sends a one-time link to a chat that
is already authenticated as that person; opening it exchanges the link for a session
cookie. Nothing is emailed, nothing has a password.

Both tokens are stored as SHA-256 digests: a leaked database row cannot be replayed
as a login.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginToken, Session, User, utcnow

COOKIE_NAME = "gutschwein_session"
LOGIN_TOKEN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=90)
# How stale `last_used_at` may get before it is worth a write. The column exists so
# the access screen can say "yesterday" about a device, and it was being rewritten on
# every single request — a write transaction, and the lock that comes with it, on
# paths that are otherwise pure reads.
LAST_USED_RESOLUTION = timedelta(minutes=15)


def digest(token: str) -> str:
    """The only form a token is ever stored or compared in."""
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """SQLite drops the timezone, so a stored timestamp comes back naive.

    Comparing that with an aware "now" raises TypeError — and it would raise
    inside the expiry check, i.e. exactly where a wrong answer is dangerous.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def issue_login_token(session: AsyncSession, user: User) -> str:
    """A single-use token for the link the bot sends. Returns the plaintext."""
    token = secrets.token_urlsafe(32)
    session.add(
        LoginToken(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=utcnow() + LOGIN_TOKEN_TTL,
        )
    )
    await session.commit()
    return token


async def redeem_login_token(session: AsyncSession, token: str) -> User | None:
    """Consume a link token. Returns its member, or None for anything suspect.

    Does not commit: the caller commits the consumption together with the session
    it opens, so a link is spent exactly when someone was signed in with it.

    Consuming is one conditional UPDATE, and it is the first write of the request,
    so it takes SQLite's writer lock before anything is read — the approach of
    `services.lock_voucher_or_404`. Reading the row first and writing afterwards
    let five simultaneous requests all see "unused" and all open a session (F5).
    A request that arrives while another holds the lock waits for its commit and
    then matches nothing.
    """
    now = utcnow()
    hashed = digest(token)
    # Used, expired, or unknown — all the same answer, so nothing is learnt by trying.
    consumed = await session.execute(
        update(LoginToken)
        .where(
            LoginToken.token_hash == hashed,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at >= now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        return None
    user_id = (
        await session.execute(select(LoginToken.user_id).where(LoginToken.token_hash == hashed))
    ).scalar_one()
    return await session.get(User, user_id)


async def open_session(session: AsyncSession, user: User) -> str:
    """Start a browser session. Returns the plaintext cookie value."""
    token = secrets.token_urlsafe(32)
    session.add(
        Session(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=utcnow() + SESSION_TTL,
        )
    )
    await session.commit()
    return token


async def resolve_session(session: AsyncSession, token: str) -> User | None:
    row = (
        await session.execute(select(Session).where(Session.token_hash == digest(token)))
    ).scalar_one_or_none()
    now = utcnow()
    if row is None or _as_utc(row.expires_at) < now:
        return None
    if row.last_used_at is None or now - _as_utc(row.last_used_at) > LAST_USED_RESOLUTION:
        row.last_used_at = now
        await session.commit()
    return await session.get(User, row.user_id)


async def close_session(session: AsyncSession, token: str) -> None:
    row = (
        await session.execute(select(Session).where(Session.token_hash == digest(token)))
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginToken, Session, User, utcnow

COOKIE_NAME = "gutschwein_session"
LOGIN_TOKEN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=90)


def _digest(token: str) -> str:
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
            token_hash=_digest(token),
            user_id=user.id,
            expires_at=utcnow() + LOGIN_TOKEN_TTL,
        )
    )
    await session.commit()
    return token


async def redeem_login_token(session: AsyncSession, token: str) -> User | None:
    """Exchange a link token for a session. Returns None for anything suspect."""
    row = (
        await session.execute(
            select(LoginToken).where(LoginToken.token_hash == _digest(token))
        )
    ).scalar_one_or_none()

    now = utcnow()
    # Used, expired, or unknown — all the same answer, so nothing is learnt by trying.
    if row is None or row.used_at is not None or _as_utc(row.expires_at) < now:
        return None

    row.used_at = now
    await session.commit()
    return await session.get(User, row.user_id)


async def open_session(session: AsyncSession, user: User) -> str:
    """Start a browser session. Returns the plaintext cookie value."""
    token = secrets.token_urlsafe(32)
    session.add(
        Session(
            token_hash=_digest(token),
            user_id=user.id,
            expires_at=utcnow() + SESSION_TTL,
        )
    )
    await session.commit()
    return token


async def resolve_session(session: AsyncSession, token: str) -> User | None:
    row = (
        await session.execute(select(Session).where(Session.token_hash == _digest(token)))
    ).scalar_one_or_none()
    if row is None or _as_utc(row.expires_at) < utcnow():
        return None
    row.last_used_at = utcnow()
    await session.commit()
    return await session.get(User, row.user_id)


async def close_session(session: AsyncSession, token: str) -> None:
    row = (
        await session.execute(select(Session).where(Session.token_hash == _digest(token)))
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()

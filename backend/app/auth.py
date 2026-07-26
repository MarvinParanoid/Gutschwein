"""Telegram Mini App authentication.

The client sends `Authorization: tma <initData>` — verbatim the string Telegram
puts in `window.Telegram.WebApp.initData`. We verify the HMAC signature with the
bot token, check auth_date freshness and whitelist membership. There are no
sessions or app-issued tokens: initData is itself a signed identity bearer.

The signature check is aiogram's: the data-check-string covers every field except
`hash` — including `signature`, which modern clients always send. Excluding it
(as an earlier version here did) breaks every real request while passing
hand-built test fixtures.
"""

import json
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import parse_qsl

from aiogram.utils.web_app import check_webapp_signature
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.i18n import language_for, t
from app.models import User, utcnow
from app.sessions import resolve_session


class TelegramUser(dict):
    """The parsed `user` block from initData."""

    @property
    def id(self) -> int:
        return int(self["id"])


def verify_init_data(init_data: str, bot_token: str, max_age: int) -> TelegramUser:
    """Raises ValueError carrying a message *key*, so the caller can translate."""
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    if "hash" not in data:
        raise ValueError("error.init_data_no_hash")
    if not check_webapp_signature(bot_token, init_data):
        raise ValueError("error.init_data_bad_signature")

    auth_date = int(data.get("auth_date", "0"))
    age = (datetime.now(UTC) - datetime.fromtimestamp(auth_date, UTC)).total_seconds()
    if age > max_age:
        raise ValueError("error.init_data_expired")

    raw_user = data.get("user")
    if not raw_user:
        raise ValueError("error.init_data_no_user")
    return TelegramUser(json.loads(raw_user))


async def upsert_user(session: AsyncSession, tg: TelegramUser) -> User:
    user = (
        await session.execute(select(User).where(User.telegram_id == tg.id))
    ).scalar_one_or_none()
    if user is None:
        user = User(telegram_id=tg.id)
        session.add(user)
    user.first_name = tg.get("first_name", "") or ""
    user.last_name = tg.get("last_name", "") or ""
    user.username = tg.get("username", "") or ""
    user.language = language_for(tg.get("language_code"), settings.default_language)
    user.last_seen_at = utcnow()
    await session.commit()
    await session.refresh(user)
    return user


def check_allowed(user: User) -> User:
    """Membership is checked on every request, not only at login.

    Two kinds of member, one rule each. A Telegram member is allowed exactly
    while their id is in ALLOWED_TELEGRAM_IDS — removing it locks them out on the
    next request, including a browser session opened while they still had access.
    A member invited from the console has no Telegram id; for them the row itself
    is the membership, and revoking means deleting it (`app.invite --revoke`).
    """
    if user.telegram_id is None:
        return user
    if user.telegram_id not in settings.allowed_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("error.no_access", user.language, telegram_id=user.telegram_id),
        )
    return user


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[int | None, Header()] = None,
    sparschwein_session: Annotated[str | None, Cookie()] = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> User:
    language = language_for(accept_language, settings.default_language)
    if settings.dev_mode and x_dev_user is not None:
        # Name includes the id so several fake members stay distinguishable locally.
        return await upsert_user(
            session, TelegramUser({"id": x_dev_user, "first_name": f"Dev {x_dev_user}"})
        )

    # Outside Telegram (the PWA) the identity comes from the session cookie.
    if sparschwein_session:
        user = await resolve_session(session, sparschwein_session)
        if user is not None:
            return check_allowed(user)

    if not authorization or not authorization.lower().startswith("tma "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            t("error.auth_required", language),
        )
    if not settings.bot_token:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, t("error.no_bot_token", language)
        )

    try:
        tg = verify_init_data(
            authorization[4:].strip(), settings.bot_token, settings.init_data_max_age
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, t(str(exc), language)
        ) from exc

    if tg.id not in settings.allowed_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("error.no_access", language, telegram_id=tg.id),
        )

    return await upsert_user(session, tg)


CurrentUser = Annotated[User, Depends(get_current_user)]

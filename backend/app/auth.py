"""Telegram Mini App authentication.

The client sends `Authorization: tma <initData>` — verbatim the string Telegram
puts in `window.Telegram.WebApp.initData`. We verify the HMAC signature with the
bot token, check auth_date freshness and whitelist membership. There are no
sessions or app-issued tokens: initData is itself a signed identity bearer.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User, utcnow


class TelegramUser(dict):
    """The parsed `user` block from initData."""

    @property
    def id(self) -> int:
        return int(self["id"])


def verify_init_data(init_data: str, bot_token: str, max_age: int) -> TelegramUser:
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("initData без hash")

    # `signature` is Telegram's own third-party-validation field and is excluded
    # from the data-check-string.
    data.pop("signature", None)
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))

    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise ValueError("Неверная подпись initData")

    auth_date = int(data.get("auth_date", "0"))
    age = (datetime.now(UTC) - datetime.fromtimestamp(auth_date, UTC)).total_seconds()
    if age > max_age:
        raise ValueError("initData просрочен")

    raw_user = data.get("user")
    if not raw_user:
        raise ValueError("initData без блока user")
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
    user.last_seen_at = utcnow()
    await session.commit()
    await session.refresh(user)
    return user


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[int | None, Header()] = None,
) -> User:
    if settings.dev_mode and x_dev_user is not None:
        # Name includes the id so several fake members stay distinguishable locally.
        return await upsert_user(
            session, TelegramUser({"id": x_dev_user, "first_name": f"Dev {x_dev_user}"})
        )

    if not authorization or not authorization.lower().startswith("tma "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Нужен заголовок Authorization: tma <initData>",
        )
    if not settings.bot_token:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "BOT_TOKEN не сконфигурирован"
        )

    try:
        tg = verify_init_data(
            authorization[4:].strip(), settings.bot_token, settings.init_data_max_age
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    if tg.id not in settings.allowed_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Нет доступа. Передайте администратору свой Telegram ID: {tg.id}",
        )

    return await upsert_user(session, tg)


CurrentUser = Annotated[User, Depends(get_current_user)]

"""Login for the browser (PWA).

The link the bot sends is the credential; this exchanges it for a cookie. Trust
still originates in Telegram — the link was delivered to a chat that only that
person can read.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, TelegramUser, check_allowed, upsert_user
from app.config import settings
from app.db import get_session
from app.schemas import UserOut
from app.sessions import (
    COOKIE_NAME,
    SESSION_TTL,
    close_session,
    issue_login_token,
    open_session,
    redeem_login_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]


class LoginRequest(BaseModel):
    token: str


@router.post("/login", response_model=UserOut)
async def login(payload: LoginRequest, response: Response, session: Session) -> UserOut:
    user = await redeem_login_token(session, payload.token)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Ссылка недействительна или уже использована. Запросите новую: /login боту",
        )
    check_allowed(user)

    token = await open_session(session, user)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,  # unreachable from JavaScript, so an XSS cannot steal it
        secure=True,
        samesite="lax",  # blocks the cookie on cross-site POSTs, which is our CSRF defence
        path="/",
    )
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user: CurrentUser,
    session: Session,
    response: Response,
    sparschwein_session: Annotated[str | None, Cookie()] = None,
) -> None:
    """Drops this browser's session; other devices keep theirs."""
    if sparschwein_session:
        await close_session(session, sparschwein_session)
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/dev-token", include_in_schema=False)
async def dev_token(session: Session) -> dict[str, str]:
    """A login token without Telegram — for the end-to-end tests only.

    Gated on DEV_MODE, exactly like the X-Dev-User header: production runs with
    it off, and then this route does not exist as far as a caller can tell.
    """
    if not settings.dev_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    user = await upsert_user(session, TelegramUser({"id": 1000, "first_name": "Dev 1000"}))
    return {"token": await issue_login_token(session, user)}

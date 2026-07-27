"""Login for the browser (PWA).

The link the bot sends is the credential; this exchanges it for a cookie. Trust
still originates in Telegram — the link was delivered to a chat that only that
person can read.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, TelegramUser, check_allowed, upsert_user
from app.config import settings
from app.db import get_session
from app.i18n import Message, group_t
from app.models import Session as SessionRow
from app.models import User
from app.notify import notify
from app.schemas import InviteOut, InviteRequest, SessionOut, UserOut
from app.sessions import (
    COOKIE_NAME,
    LOGIN_TOKEN_TTL,
    SESSION_TTL,
    close_session,
    digest,
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
            Message("error.login_link_dead"),
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
    gutschwein_session: Annotated[str | None, Cookie()] = None,
) -> None:
    """Drops this browser's session; other devices keep theirs."""
    if gutschwein_session:
        await close_session(session, gutschwein_session)
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    user: CurrentUser,
    session: Session,
    gutschwein_session: Annotated[str | None, Cookie()] = None,
) -> list[SessionOut]:
    """Every signed-in browser in the household, not only the caller's.

    One shared family, one shared list: the point is to notice a device that
    should not be there, and you cannot notice it in a list you cannot see.
    Telegram itself needs no session, so the Mini App never appears here.
    """
    rows = await session.execute(
        select(SessionRow, User)
        .join(User, User.id == SessionRow.user_id)
        .order_by(SessionRow.last_used_at.desc().nullslast(), SessionRow.id.desc())
    )
    mine = digest(gutschwein_session) if gutschwein_session else None
    return [
        SessionOut(
            id=row.id,
            member=member.display_name,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            current=row.token_hash == mine,
        )
        for row, member in rows.all()
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    user: CurrentUser,
    session: Session,
    session_id: int,
    gutschwein_session: Annotated[str | None, Cookie()] = None,
) -> None:
    row = await session.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, Message("error.session_not_found"))
    # Signing yourself out from the list would look like the app breaking; the
    # logout button is right there for that.
    if gutschwein_session and row.token_hash == digest(gutschwein_session):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, Message("error.session_is_current"))
    await session.delete(row)
    await session.commit()


@router.post("/sessions/others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_sessions(
    user: CurrentUser,
    session: Session,
    gutschwein_session: Annotated[str | None, Cookie()] = None,
) -> None:
    """The lost-phone button: everything except the browser asking."""
    keep = digest(gutschwein_session) if gutschwein_session else None
    statement = delete(SessionRow)
    if keep is not None:
        statement = statement.where(SessionRow.token_hash != keep)
    await session.execute(statement)
    await session.commit()


@router.post("/invite", response_model=InviteOut)
async def invite(payload: InviteRequest, user: CurrentUser, session: Session) -> InviteOut:
    """A one-time login link, minted from inside the app instead of over ssh.

    With a name it creates a member who has no Telegram account; without one it
    is a second device for whoever asked. Either way the link is the same
    credential the bot hands out, and the family chat is told it happened —
    minting a way in is exactly the event nobody should miss.
    """
    if not settings.webapp_url.startswith("https://"):
        raise HTTPException(status.HTTP_409_CONFLICT, Message("error.no_webapp_url"))

    name = payload.name.strip()
    if name:
        member = User(first_name=name, language=user.language)
        session.add(member)
        await session.flush()
    else:
        member = user

    token = await issue_login_token(session, member)
    await notify(
        group_t(
            "notify.invited" if name else "notify.new_device",
            actor=user.display_name,
            member=member.display_name,
        )
    )
    return InviteOut(
        url=f"{settings.webapp_url}/login#{token}",
        minutes=int(LOGIN_TOKEN_TTL.total_seconds() // 60),
        member=member.display_name,
    )


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

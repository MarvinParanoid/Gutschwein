"""Membership without Telegram: `python -m app.invite "Anna"`.

The app can run with no bot at all, but until now the only way to get a session
was a link the bot sent. This is the same link, handed out from the server
console instead — same one-time token, same ten minutes, same cookie afterwards.
The trust anchor moves from "Telegram vouches that this chat is Anna" to
"whoever has a shell on this server vouches for it", which for a self-hosted
household is the shorter chain.

    python -m app.invite "Anna"        # create a member, print a login link
    python -m app.invite --link 3      # another link for member 3
    python -m app.invite --list        # who exists
    python -m app.invite --revoke 3    # remove them and end their sessions
"""

import argparse
import asyncio
import sys

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.i18n import default_language
from app.models import Session, User
from app.sessions import LOGIN_TOKEN_TTL, issue_login_token


def _login_url(token: str) -> str:
    if settings.webapp_url.startswith("https://"):
        return f"{settings.webapp_url}/login#{token}"
    # Without a public URL the token is still valid; only the address is unknown.
    return f"<WEBAPP_URL>/login#{token}"


def _describe(user: User) -> str:
    kind = "telegram" if user.telegram_id is not None else "console"
    return f"  {user.id:>3}  {user.display_name:<24} {kind}"


async def create(name: str) -> None:
    async with SessionLocal() as session:
        user = User(first_name=name, language=default_language())
        session.add(user)
        await session.flush()
        token = await issue_login_token(session, user)
        minutes = int(LOGIN_TOKEN_TTL.total_seconds() // 60)
        print(f"member {user.id} created: {user.display_name}")
        print(f"login link (valid {minutes} minutes, single use):\n{_login_url(token)}")
        print("Open it in the browser that should be signed in. Do not forward it.")


async def link(user_id: int) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            sys.exit(f"no member with id {user_id}")
        token = await issue_login_token(session, user)
        print(_login_url(token))


async def listing() -> None:
    async with SessionLocal() as session:
        users = (await session.execute(select(User).order_by(User.id))).scalars().all()
    if not users:
        print("no members yet")
        return
    print("\n".join(_describe(user) for user in users))


async def revoke(user_id: int) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            sys.exit(f"no member with id {user_id}")
        if user.telegram_id is not None:
            sys.exit(
                f"member {user_id} signs in through Telegram — remove {user.telegram_id} "
                "from ALLOWED_TELEGRAM_IDS instead, and restart"
            )
        # Sessions first: an open browser must lose access, not just the account.
        await session.execute(delete(Session).where(Session.user_id == user_id))
        await session.delete(user)
        await session.commit()
        print(f"member {user_id} removed, their sessions ended")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.invite", description=__doc__)
    parser.add_argument("name", nargs="?", help="name of the member to create")
    parser.add_argument("--link", type=int, metavar="ID", help="new login link for a member")
    parser.add_argument("--list", action="store_true", help="list members")
    parser.add_argument("--revoke", type=int, metavar="ID", help="remove a console member")
    args = parser.parse_args()

    if args.list:
        asyncio.run(listing())
    elif args.link is not None:
        asyncio.run(link(args.link))
    elif args.revoke is not None:
        asyncio.run(revoke(args.revoke))
    elif args.name:
        asyncio.run(create(args.name))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

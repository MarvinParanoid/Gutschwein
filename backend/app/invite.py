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

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.i18n import default_language
from app.models import Comment, Event, Session, User, Voucher
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


async def _history(session: AsyncSession, user_id: int) -> str:
    """A human summary of what this member left behind, empty when nothing."""
    counts = {
        "vouchers": select(func.count())
        .select_from(Voucher)
        .where(or_(Voucher.created_by_id == user_id, Voucher.used_by_id == user_id)),
        "comments": select(func.count()).select_from(Comment).where(Comment.author_id == user_id),
        "events": select(func.count()).select_from(Event).where(Event.actor_id == user_id),
    }
    found = []
    for label, query in counts.items():
        total = (await session.execute(query)).scalar_one()
        if total:
            found.append(f"{total} {label}")
    return ", ".join(found)


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
        # Vouchers, comments and events point at this row, and the database now
        # refuses to leave those pointers dangling. It used to allow it, and SQLite
        # then handed the freed id to the next member created — who inherited the
        # history. Refusing is the honest answer: a member who did things cannot be
        # made never to have existed.
        traces = await _history(session, user_id)
        if traces:
            sys.exit(
                f"member {user_id} has history in the family log ({traces}) and cannot "
                f"be deleted. Ending their sessions is what locks them out:\n"
                f"  python -m app.invite --sessions-off {user_id}"
            )

        # Sessions first: an open browser must lose access, not just the account.
        await session.execute(delete(Session).where(Session.user_id == user_id))
        await session.delete(user)
        await session.commit()
        print(f"member {user_id} removed, their sessions ended")


async def sessions_off(user_id: int) -> None:
    """Lock a member out without erasing what they did."""
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            sys.exit(f"no member with id {user_id}")
        result = await session.execute(delete(Session).where(Session.user_id == user_id))
        await session.commit()
        print(f"{result.rowcount} session(s) ended for member {user_id}")
        if user.telegram_id is not None:
            print(
                f"they sign in through Telegram — also remove {user.telegram_id} "
                "from ALLOWED_TELEGRAM_IDS, or the next request lets them back in"
            )


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.invite", description=__doc__)
    parser.add_argument("name", nargs="?", help="name of the member to create")
    parser.add_argument("--link", type=int, metavar="ID", help="new login link for a member")
    parser.add_argument("--list", action="store_true", help="list members")
    parser.add_argument("--revoke", type=int, metavar="ID", help="remove a console member")
    parser.add_argument(
        "--sessions-off",
        type=int,
        metavar="ID",
        dest="sessions_off",
        help="end a member's sessions without deleting them",
    )
    args = parser.parse_args()

    if args.list:
        asyncio.run(listing())
    elif args.link is not None:
        asyncio.run(link(args.link))
    elif args.revoke is not None:
        asyncio.run(revoke(args.revoke))
    elif args.sessions_off is not None:
        asyncio.run(sessions_off(args.sessions_off))
    elif args.name:
        asyncio.run(create(args.name))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

"""Membership without Telegram: `python -m app.invite "Anna"`.

The app can run with no bot at all, but until now the only way to get a session
was a link the bot sent. This is the same link, handed out from the server
console instead — same one-time token, same ten minutes, same cookie afterwards.
The trust anchor moves from "Telegram vouches that this chat is Anna" to
"whoever has a shell on this server vouches for it", which for a self-hosted
household is the shorter chain. A member created here is a console root: the
anchor for whoever they invite in the app (see app.membership).

    python -m app.invite "Anna"            # create a member, print a login link
    python -m app.invite --link 3          # another link for member 3
    python -m app.invite --list            # who exists, and whether they get in
    python -m app.invite --confirm 3       # vouch for a member of unknown origin
    python -m app.invite --set-inviter 3 1 # …or record who invited them
    python -m app.invite --revoke 3        # end their membership, and their invitees'
    python -m app.invite --restore 3       # undo a revocation
    python -m app.invite --sessions-off 3  # sign out their devices, membership kept
    python -m app.invite --prune           # sign out devices of everyone refused now
"""

import argparse
import asyncio
import sys

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.i18n import default_language
from app.membership import MAX_CHAIN, descendants, end_access, membership
from app.models import Comment, Event, Session, User, Voucher, utcnow
from app.sessions import LOGIN_TOKEN_TTL, issue_login_token

# What --list says about a refusal, for the operator rather than the member.
REFUSALS = {
    "telegram": "refused: not in ALLOWED_TELEGRAM_IDS",
    "revoked": "refused: revoked",
    "unconfirmed": "REFUSED: origin unknown, review with --confirm or --set-inviter",
    "inviter": "refused: their inviter has no access",
    "invalid": "refused: invitation record damaged (see the log)",
}


def _login_url(token: str) -> str:
    if settings.webapp_url.startswith("https://"):
        return f"{settings.webapp_url}/login#{token}"
    # Without a public URL the token is still valid; only the address is unknown.
    return f"<WEBAPP_URL>/login#{token}"


def _kind(user: User) -> str:
    if user.telegram_id is not None:
        return "telegram"
    if user.console_root:
        return "console root"
    if user.invited_by_id is not None:
        return f"invited by {user.invited_by_id}"
    return "unconfirmed"


async def _member(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        sys.exit(f"no member with id {user_id}")
    return user


def _without_telegram(user: User, action: str) -> None:
    if user.telegram_id is not None:
        sys.exit(
            f"member {user.id} signs in through Telegram — {action} by editing "
            f"ALLOWED_TELEGRAM_IDS ({user.telegram_id}) instead, and restart"
        )


async def create(name: str) -> None:
    async with SessionLocal() as session:
        user = User(first_name=name, language=default_language(), console_root=True)
        session.add(user)
        await session.flush()
        token = await issue_login_token(session, user)
        minutes = int(LOGIN_TOKEN_TTL.total_seconds() // 60)
        print(f"member {user.id} created: {user.display_name}")
        print(f"login link (valid {minutes} minutes, single use):\n{_login_url(token)}")
        print("Open it in the browser that should be signed in. Do not forward it.")


async def link(user_id: int) -> None:
    async with SessionLocal() as session:
        user = await _member(session, user_id)
        # A link for someone who is refused would only be refused again at login.
        verdict = await membership(session, user)
        if not verdict.allowed:
            sys.exit(f"member {user_id} cannot sign in ({REFUSALS[verdict.reason]})")
        token = await issue_login_token(session, user)
        print(_login_url(token))


async def listing() -> None:
    async with SessionLocal() as session:
        users = (await session.execute(select(User).order_by(User.id))).scalars().all()
        if not users:
            print("no members yet")
            return
        counts = dict(
            (
                await session.execute(
                    select(Session.user_id, func.count()).group_by(Session.user_id)
                )
            ).all()
        )
        for user in users:
            verdict = await membership(session, user)
            access = "allowed" if verdict.allowed else REFUSALS[verdict.reason]
            print(
                f"  {user.id:>3}  {user.display_name:<24} {_kind(user):<16} "
                f"{counts.get(user.id, 0)} session(s)  {access}"
            )


async def confirm(user_id: int) -> None:
    """The operator vouches for a member nobody recorded the origin of."""
    async with SessionLocal() as session:
        user = await _member(session, user_id)
        _without_telegram(user, "confirm them")
        if user.console_root:
            sys.exit(f"member {user_id} is already a console root")
        if user.invited_by_id is not None:
            sys.exit(
                f"member {user_id} was invited by {user.invited_by_id}; their access follows "
                "that member's, and confirming them would cut that link"
            )
        user.console_root = True
        await session.commit()
        print(f"member {user_id} confirmed as a console root")


async def set_inviter(user_id: int, inviter_id: int) -> None:
    """Record who invited a member of unknown origin, so it follows their access."""
    async with SessionLocal() as session:
        user = await _member(session, user_id)
        inviter = await _member(session, inviter_id)
        _without_telegram(user, "change their access")
        if user.console_root or user.invited_by_id is not None:
            sys.exit(f"member {user_id} already has a recorded origin ({_kind(user)})")
        if inviter_id == user_id:
            sys.exit("a member cannot be their own inviter")
        # Walk up from the inviter: meeting the member there would close a cycle.
        node, steps = inviter, 0
        while node is not None and node.invited_by_id is not None and steps < MAX_CHAIN:
            if node.invited_by_id == user_id:
                sys.exit(f"member {inviter_id} was invited through {user_id}: that is a cycle")
            node = await session.get(User, node.invited_by_id)
            steps += 1
        user.invited_by_id = inviter_id
        await session.commit()
        verdict = await membership(session, user)
        state = "allowed" if verdict.allowed else REFUSALS[verdict.reason]
        print(f"member {user_id} recorded as invited by {inviter_id}: {state}")


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
    """End a membership, and with it the access of everyone invited through it.

    One transaction: the revocation, the sessions and links of the whole subtree,
    and — for a member who left nothing behind and invited nobody — the row. The
    subtree is refused by the chain check anyway; deleting their sessions as well
    means that a later --restore does not bring the old devices back with it.
    """
    async with SessionLocal() as session:
        user = await _member(session, user_id)
        _without_telegram(user, "remove them")
        below = await descendants(session, user_id)
        if user.revoked_at is None:
            user.revoked_at = utcnow()
        sessions, tokens = await end_access(session, [user_id, *below])

        # Vouchers, comments and events point at this row, and so do invitees. The
        # database refuses to leave those pointers dangling, and it used to allow
        # it — SQLite then handed the freed id to the next member created, who
        # inherited the history. Such a row stays, revoked.
        traces = await _history(session, user_id)
        deleted = not traces and not below
        if deleted:
            await session.delete(user)
        await session.commit()

    print(f"member {user_id} {'removed' if deleted else 'revoked'}")
    if below:
        print(f"  {len(below)} member(s) invited through them lose access too: {below}")
    print(f"  {sessions} session(s) and {tokens} login link(s) ended")
    if traces:
        print(f"  the row stays for the history ({traces})")


async def restore(user_id: int) -> None:
    async with SessionLocal() as session:
        user = await _member(session, user_id)
        if user.revoked_at is None:
            sys.exit(f"member {user_id} is not revoked")
        user.revoked_at = None
        await session.commit()
        verdict = await membership(session, user)
    state = "allowed" if verdict.allowed else REFUSALS[verdict.reason]
    print(f"member {user_id} restored: {state}")
    print(
        "  members invited through them get their access back too. Sessions ended "
        f"by the revocation do not return: issue new links (--link {user_id})."
    )


async def sessions_off(user_id: int) -> None:
    """Sign a member out everywhere without touching their membership."""
    async with SessionLocal() as session:
        user = await _member(session, user_id)
        sessions, tokens = await end_access(session, [user_id])
        await session.commit()
    print(f"{sessions} session(s) and {tokens} login link(s) ended for member {user_id}")
    print("  their membership is unchanged; to end it, use --revoke")
    if user.telegram_id is not None:
        print(
            f"they sign in through Telegram — also remove {user.telegram_id} "
            "from ALLOWED_TELEGRAM_IDS, or the Mini App still lets them in"
        )


async def prune() -> None:
    """Delete the sessions and unused links of every member refused right now.

    Devices, not memberships: nobody is revoked here. They cannot be used anyway;
    deleting them means that when the reason goes away — a Telegram ancestor back
    on the list — those members get in again only through a new link, not through
    whatever old browser still holds a cookie. Ending a membership is --revoke.
    """
    async with SessionLocal() as session:
        users = (await session.execute(select(User).order_by(User.id))).scalars().all()
        refused = [u.id for u in users if not (await membership(session, u)).allowed]
        sessions, tokens = await end_access(session, refused)
        await session.commit()
    print(f"{len(refused)} refused member(s): {refused}")
    print(f"  {sessions} session(s) and {tokens} login link(s) ended; memberships unchanged")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="app.invite", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("name", nargs="?", help="name of the member to create")
    parser.add_argument("--link", type=int, metavar="ID", help="new login link for a member")
    parser.add_argument("--list", action="store_true", help="list members and their access")
    parser.add_argument("--confirm", type=int, metavar="ID", help="vouch for a member")
    parser.add_argument(
        "--set-inviter",
        type=int,
        nargs=2,
        metavar=("ID", "INVITER"),
        dest="set_inviter",
        help="record who invited a member of unknown origin",
    )
    parser.add_argument("--revoke", type=int, metavar="ID", help="end a membership")
    parser.add_argument("--restore", type=int, metavar="ID", help="undo a revocation")
    parser.add_argument(
        "--sessions-off",
        type=int,
        metavar="ID",
        dest="sessions_off",
        help="sign out every device of a member, membership kept",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="sign out devices and links of everyone refused now; memberships stay",
    )
    args = parser.parse_args()

    if args.list:
        asyncio.run(listing())
    elif args.link is not None:
        asyncio.run(link(args.link))
    elif args.confirm is not None:
        asyncio.run(confirm(args.confirm))
    elif args.set_inviter is not None:
        asyncio.run(set_inviter(*args.set_inviter))
    elif args.revoke is not None:
        asyncio.run(revoke(args.revoke))
    elif args.restore is not None:
        asyncio.run(restore(args.restore))
    elif args.sessions_off is not None:
        asyncio.run(sessions_off(args.sessions_off))
    elif args.prune:
        asyncio.run(prune())
    elif args.name:
        asyncio.run(create(args.name))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

"""Who is a member of the household, decided on every request.

A Telegram member is in while their id is in ALLOWED_TELEGRAM_IDS. Everyone else
has no Telegram id, and their right to be here has to come from somewhere:

  * `console_root` — created from the server console; whoever has a shell vouched;
  * `invited_by_id` — created in the app by another member, and in only as long as
    that member is: the chain is followed up to a Telegram member on the list or
    a console root, and any broken link refuses everyone below it;
  * neither — a row from before provenance was recorded. Nobody can say who let it
    in, so it is refused until the operator says (`app.invite --confirm`,
    `--set-inviter`). Guessing in its favour is how F4 happened: a member removed
    from the list kept a back door through the people they had invited.

`revoked_at` withdraws a membership without deleting the row, which the history
still points at, and it is checked before anything else on every link.

Nothing here writes. A session or a login link of a refused member simply stops
working, and starts again if the reason goes away (a Telegram ancestor put back
on the list). `app.invite --prune` deletes those sessions and links, which ends
the devices but not the membership; only `--revoke` ends a membership.

DEV_MODE is the one deliberate exception: `X-Dev-User` and /api/auth/dev-token
let any id in without the allowlist or this check, for local work and the
end-to-end suite. It must never be on in production.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import LoginToken, Session, User

log = logging.getLogger(__name__)

# A household's invitation tree is a few levels deep. A longer chain is a corrupted
# table, not a family, and following it on every request would be the bug.
MAX_CHAIN = 16


@dataclass(frozen=True)
class Verdict:
    """`anchor` says why a member is let in; `reason` why not (an i18n suffix)."""

    anchor: str | None = None  # "telegram" | "console"
    reason: str | None = None  # "telegram" | "revoked" | "unconfirmed" | "inviter" | "invalid"

    @property
    def allowed(self) -> bool:
        return self.anchor is not None


def _invalid(user: User, why: str) -> Verdict:
    log.warning("membership of user %s refused: %s", user.id, why)
    return Verdict(reason="invalid")


async def membership(session: AsyncSession, user: User) -> Verdict:
    """Follow the invitation chain from `user` to the anchor it rests on."""
    seen: set[int] = set()
    node = user
    while True:
        if node.id in seen:
            return _invalid(user, f"invitation cycle through user {node.id}")
        if len(seen) >= MAX_CHAIN:
            return _invalid(user, f"invitation chain longer than {MAX_CHAIN}")
        seen.add(node.id)
        own = node.id == user.id

        if node.revoked_at is not None:
            return Verdict(reason="revoked" if own else "inviter")
        if node.telegram_id is not None:
            # A Telegram member is their own anchor; nobody invites them in the app.
            if node.console_root or node.invited_by_id is not None:
                return _invalid(user, f"user {node.id} has Telegram and app provenance")
            if node.telegram_id in settings.allowed_ids:
                return Verdict(anchor="telegram")
            return Verdict(reason="telegram" if own else "inviter")
        if node.console_root:
            if node.invited_by_id is not None:
                return _invalid(user, f"user {node.id} is both a root and invited")
            return Verdict(anchor="console")
        if node.invited_by_id is None:
            return Verdict(reason="unconfirmed" if own else "inviter")

        parent = await session.get(User, node.invited_by_id)
        if parent is None:
            return _invalid(user, f"inviter {node.invited_by_id} of user {node.id} is missing")
        node = parent


async def descendants(session: AsyncSession, user_id: int) -> list[int]:
    """Everyone invited by `user_id`, directly or further down, in no order."""
    found: list[int] = []
    seen = {user_id}
    frontier = [user_id]
    while frontier:
        rows = await session.execute(select(User.id).where(User.invited_by_id.in_(frontier)))
        frontier = [i for i in rows.scalars().all() if i not in seen]
        seen.update(frontier)
        found.extend(frontier)
    return found


async def end_access(session: AsyncSession, user_ids: list[int]) -> tuple[int, int]:
    """Delete the sessions and login links of these members. Does not commit.

    Returns (sessions, tokens). Used tokens go too: they are dead already, and
    leaving them would only make the count lie about what was cut off.
    """
    if not user_ids:
        return 0, 0
    sessions = await session.execute(delete(Session).where(Session.user_id.in_(user_ids)))
    tokens = await session.execute(delete(LoginToken).where(LoginToken.user_id.in_(user_ids)))
    return sessions.rowcount, tokens.rowcount


async def unconfirmed(session: AsyncSession) -> list[User]:
    """Members from before provenance was recorded, still waiting for the operator."""
    rows = await session.execute(
        select(User)
        .where(
            User.telegram_id.is_(None),
            User.console_root.is_(False),
            User.invited_by_id.is_(None),
            User.revoked_at.is_(None),
        )
        .order_by(User.id)
    )
    return list(rows.scalars().all())


async def warn_about_unconfirmed(session: AsyncSession) -> None:
    """Said at every start until it is dealt with: these members cannot get in."""
    waiting = await unconfirmed(session)
    if not waiting:
        return
    names = ", ".join(f"{u.id} ({u.display_name})" for u in waiting)
    log.warning(
        "%s member(s) without recorded provenance are refused until reviewed: %s. "
        "Run `python -m app.invite --list`, then --confirm ID or --set-inviter ID INVITER.",
        len(waiting),
        names,
    )

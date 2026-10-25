"""Members without Telegram, and where their access comes from (F4).

An in-app invitation used to create a member whose access rested on nothing but
their own row: removing the inviter from ALLOWED_TELEGRAM_IDS left everyone they
had invited inside, able to invite further. Now every member without Telegram
hangs off a console root or a Telegram member still on the list, and that chain
is checked on every request — through the browsers that are already signed in
and the links that have not been opened yet.

Each test gets its own Telegram ids and names: the suite shares one database.
"""

import itertools
import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import invite
from app.auth import TelegramUser, upsert_user
from app.config import settings
from app.db import SessionLocal
from app.i18n import RU, t
from app.main import app
from app.membership import MAX_CHAIN, membership
from app.models import LoginToken, Session, User, Voucher
from app.sessions import issue_login_token
from tests.test_auth import TOKEN, sign

_ids = itertools.count(880_001)


@pytest.fixture(autouse=True)
def public_url(monkeypatch, client: TestClient):
    """`client` is here for its side effect: it runs the migrations."""
    monkeypatch.setattr(settings, "webapp_url", "https://example.com")
    monkeypatch.setattr(settings, "allowed_telegram_ids", "")


@pytest.fixture
async def browsers() -> AsyncIterator:
    """Separate cookie jars, one per device. No dev header: cookies decide."""
    opened: list[httpx.AsyncClient] = []

    def open_browser() -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        browser = httpx.AsyncClient(transport=transport, base_url="https://testserver")
        opened.append(browser)
        return browser

    yield open_browser
    for browser in opened:
        await browser.aclose()


def _allow(monkeypatch, *telegram_ids: int) -> None:
    monkeypatch.setattr(settings, "allowed_telegram_ids", ",".join(map(str, telegram_ids)))


async def _telegram_member(name: str) -> tuple[User, str]:
    """A Telegram member and the link the bot's /login would send them."""
    async with SessionLocal() as db:
        user = await upsert_user(db, TelegramUser({"id": next(_ids), "first_name": name}))
        return user, await issue_login_token(db, user)


async def _console_root(name: str) -> tuple[User, str]:
    async with SessionLocal() as db:
        user = User(first_name=name, console_root=True)
        db.add(user)
        await db.flush()
        token = await issue_login_token(db, user)
        await db.commit()
        return user, token


async def _signed_in(browser: httpx.AsyncClient, token: str) -> httpx.AsyncClient:
    assert (await browser.post("/api/auth/login", json={"token": token})).status_code == 200
    return browser


async def _invite(browser: httpx.AsyncClient, name: str) -> str:
    response = await browser.post("/api/auth/invite", json={"name": name})
    assert response.status_code == 200
    return response.json()["url"].split("/login#")[1]


async def _row(name: str) -> User:
    async with SessionLocal() as db:
        return (await db.execute(select(User).where(User.first_name == name))).scalar_one()


async def _verdict(user_id: int):
    async with SessionLocal() as db:
        return await membership(db, await db.get(User, user_id))


async def _credentials(user_id: int) -> tuple[int, int]:
    async with SessionLocal() as db:
        sessions = await db.execute(select(Session).where(Session.user_id == user_id))
        tokens = await db.execute(select(LoginToken).where(LoginToken.user_id == user_id))
        return len(sessions.all()), len(tokens.all())


def _refusal(response: httpx.Response, reason: str) -> bool:
    return response.status_code == 403 and response.json()["detail"] == t(
        f"error.membership_{reason}", RU
    )


# --- chains -------------------------------------------------------------------


async def test_a_telegram_members_guest_gets_in_and_remembers_who_invited_them(
    monkeypatch, browsers
) -> None:
    host, token = await _telegram_member("Chain-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)

    guest = await _signed_in(browsers(), await _invite(hosting, "Chain-Guest"))

    assert (await guest.get("/api/vouchers")).status_code == 200
    row = await _row("Chain-Guest")
    assert (row.invited_by_id, row.console_root, row.telegram_id) == (host.id, False, None)


async def test_removing_the_inviter_locks_out_their_guests_sessions_and_links(
    monkeypatch, browsers
) -> None:
    """F4 itself: the back door through the people a removed member invited."""
    host, token = await _telegram_member("F4-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)
    guest = await _signed_in(browsers(), await _invite(hosting, "F4-Guest"))
    unopened = await _invite(hosting, "F4-Later")

    _allow(monkeypatch)  # the host is taken off the list

    assert (await hosting.get("/api/vouchers")).status_code == 403
    assert _refusal(await guest.get("/api/vouchers"), "inviter")
    assert _refusal(await guest.post("/api/auth/invite", json={}), "inviter")
    assert _refusal(await browsers().post("/api/auth/login", json={"token": unopened}), "inviter")


async def test_the_whole_subtree_follows_its_telegram_anchor(monkeypatch, browsers) -> None:
    host, token = await _telegram_member("Tree-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)
    child = await _signed_in(browsers(), await _invite(hosting, "Tree-Child"))
    grandchild = await _signed_in(browsers(), await _invite(child, "Tree-Grandchild"))
    assert (await _row("Tree-Grandchild")).invited_by_id == (await _row("Tree-Child")).id

    _allow(monkeypatch)
    assert _refusal(await child.get("/api/me"), "inviter")
    assert _refusal(await grandchild.get("/api/me"), "inviter")

    # Access depends on the anchor as it is now: putting the host back restores the
    # subtree, through sessions that nobody deleted.
    _allow(monkeypatch, host.telegram_id)
    assert (await child.get("/api/me")).status_code == 200
    assert (await grandchild.get("/api/me")).status_code == 200


async def test_a_console_root_anchors_a_household_without_telegram(browsers) -> None:
    """Empty allowlist, no bot: the deployment that has only the console."""
    _root, token = await _console_root("Console-Root")
    rooted = await _signed_in(browsers(), token)
    child = await _signed_in(browsers(), await _invite(rooted, "Console-Child"))
    grandchild = await _signed_in(browsers(), await _invite(child, "Console-Grandchild"))

    for browser in (rooted, child, grandchild):
        assert (await browser.get("/api/vouchers")).status_code == 200


async def test_a_mixed_family_keeps_its_member_without_telegram(monkeypatch, browsers) -> None:
    host, token = await _telegram_member("Mixed-Host")
    _allow(monkeypatch, host.telegram_id, 1000)
    hosting = await _signed_in(browsers(), token)
    grandma = await _signed_in(browsers(), await _invite(hosting, "Mixed-Grandma"))

    # Someone else's change to the list does not touch her.
    _allow(monkeypatch, host.telegram_id)
    assert (await grandma.get("/api/vouchers")).status_code == 200


# --- revocation ---------------------------------------------------------------


async def test_revoking_a_member_takes_their_invitees_and_keeps_the_history(browsers) -> None:
    root, token = await _console_root("Revoke-Root")
    rooted = await _signed_in(browsers(), token)
    middle = await _signed_in(browsers(), await _invite(rooted, "Revoke-Middle"))
    leaf = await _signed_in(browsers(), await _invite(middle, "Revoke-Leaf"))
    pending = await _invite(leaf, "Revoke-Pending")
    created = await middle.post("/api/vouchers", json={"merchant": "Revoke-Card"})
    assert created.status_code == 201
    middle_row, leaf_row = await _row("Revoke-Middle"), await _row("Revoke-Leaf")

    await invite.revoke(middle_row.id)

    # Their devices are signed out, so the cookie identifies nobody any more.
    assert (await middle.get("/api/me")).status_code == 401
    assert (await leaf.get("/api/me")).status_code == 401
    assert (await browsers().post("/api/auth/login", json={"token": pending})).status_code == 401
    assert (await rooted.get("/api/me")).status_code == 200
    for user_id in (middle_row.id, leaf_row.id, (await _row("Revoke-Pending")).id):
        assert await _credentials(user_id) == (0, 0)
    assert (await _verdict(middle_row.id)).reason == "revoked"
    assert (await _verdict(leaf_row.id)).reason == "inviter"

    # The card still says who added it.
    async with SessionLocal() as db:
        card = await db.get(Voucher, created.json()["id"])
        assert card.created_by_id == middle_row.id
    assert (await _row("Revoke-Middle")).revoked_at is not None
    assert root.id  # untouched above


async def test_revoking_someone_with_invitees_keeps_the_row(browsers) -> None:
    """No history, but invitees point at it: deleting would be a traceback."""
    _root, token = await _console_root("Keep-Root")
    rooted = await _signed_in(browsers(), token)
    parent = await _signed_in(browsers(), await _invite(rooted, "Keep-Parent"))
    await _invite(parent, "Keep-Child")
    parent_row = await _row("Keep-Parent")

    await invite.revoke(parent_row.id)

    row = await _row("Keep-Parent")
    assert row.revoked_at is not None
    assert (await _row("Keep-Child")).invited_by_id == row.id


async def test_restoring_brings_back_the_membership_not_the_devices(browsers, capsys) -> None:
    _root, token = await _console_root("Restore-Root")
    rooted = await _signed_in(browsers(), token)
    parent = await _signed_in(browsers(), await _invite(rooted, "Restore-Parent"))
    child = await _signed_in(browsers(), await _invite(parent, "Restore-Child"))
    parent_row, child_row = await _row("Restore-Parent"), await _row("Restore-Child")
    await invite.revoke(parent_row.id)

    await invite.restore(parent_row.id)

    assert (await _verdict(parent_row.id)).allowed
    assert (await _verdict(child_row.id)).allowed
    # The sessions the revocation ended stay ended.
    assert (await parent.get("/api/me")).status_code == 401
    assert (await child.get("/api/me")).status_code == 401
    capsys.readouterr()
    await invite.link(parent_row.id)
    fresh = capsys.readouterr().out.strip().split("/login#")[1]
    assert (await browsers().post("/api/auth/login", json={"token": fresh})).status_code == 200


async def test_a_revoked_root_is_refused_before_its_anchor_counts(browsers) -> None:
    root, token = await _console_root("Revoked-Root")
    rooted = await _signed_in(browsers(), token)
    async with SessionLocal() as db:
        # Revoked without the cleanup, so the session is still there to be judged.
        await db.execute(update(User).where(User.id == root.id).values(revoked_at=root.created_at))
        await db.commit()

    assert _refusal(await rooted.get("/api/me"), "revoked")


async def test_signing_out_devices_is_not_revoking(browsers) -> None:
    _root, token = await _console_root("Devices-Root")
    rooted = await _signed_in(browsers(), token)
    member = await _signed_in(browsers(), await _invite(rooted, "Devices-Member"))
    child = await _signed_in(browsers(), await _invite(member, "Devices-Child"))
    member_row = await _row("Devices-Member")
    async with SessionLocal() as db:
        await issue_login_token(db, await db.get(User, member_row.id))

    await invite.sessions_off(member_row.id)

    assert await _credentials(member_row.id) == (0, 0)
    assert (await member.get("/api/me")).status_code == 401
    assert (await _verdict(member_row.id)).allowed
    # Their invitees keep their own devices.
    assert (await child.get("/api/me")).status_code == 200


async def test_pruning_signs_out_devices_but_keeps_the_membership(
    monkeypatch, browsers, capsys
) -> None:
    host, token = await _telegram_member("Prune-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)
    guest = await _signed_in(browsers(), await _invite(hosting, "Prune-Guest"))
    guest_row = await _row("Prune-Guest")
    bystander_root, bystander_token = await _console_root("Prune-Bystander")
    bystander = await _signed_in(browsers(), bystander_token)

    _allow(monkeypatch)
    await invite.prune()

    # Only the refused lost their devices; nobody was revoked.
    assert await _credentials(guest_row.id) == (0, 0)
    assert (await _row("Prune-Guest")).revoked_at is None
    assert (await bystander.get("/api/me")).status_code == 200

    # The host is back on the list: the guest is a member again, signs in with a
    # new link — and the old browser stays signed out.
    _allow(monkeypatch, host.telegram_id)
    assert (await _verdict(guest_row.id)).allowed
    assert (await guest.get("/api/me")).status_code == 401
    capsys.readouterr()
    await invite.link(guest_row.id)
    fresh = capsys.readouterr().out.strip().split("/login#")[1]
    assert (await browsers().post("/api/auth/login", json={"token": fresh})).status_code == 200
    assert bystander_root.id


async def test_a_failed_revocation_changes_nothing(browsers, monkeypatch) -> None:
    _root, token = await _console_root("Atomic-Root")
    rooted = await _signed_in(browsers(), token)
    member = await _signed_in(browsers(), await _invite(rooted, "Atomic-Member"))
    member_row = await _row("Atomic-Member")
    real = invite.end_access

    async def cleanup_then_fail(session, user_ids):
        await real(session, user_ids)
        raise RuntimeError("disk full")

    monkeypatch.setattr(invite, "end_access", cleanup_then_fail)
    with pytest.raises(RuntimeError):
        await invite.revoke(member_row.id)

    assert (await _row("Atomic-Member")).revoked_at is None
    assert (await _credentials(member_row.id))[0] == 1
    assert (await member.get("/api/me")).status_code == 200


# --- unknown and damaged provenance ------------------------------------------


async def test_a_member_of_unknown_origin_waits_for_the_operator(browsers, capsys) -> None:
    async with SessionLocal() as db:
        legacy = User(first_name="Legacy-Member")  # no root, no inviter: nobody vouched
        db.add(legacy)
        await db.flush()
        token = await issue_login_token(db, legacy)
        await db.commit()

    assert _refusal(await browsers().post("/api/auth/login", json={"token": token}), "unconfirmed")
    with pytest.raises(SystemExit) as refused:
        await invite.link(legacy.id)
    assert "origin unknown" in str(refused.value)

    await invite.confirm(legacy.id)
    capsys.readouterr()
    await invite.link(legacy.id)
    fresh = capsys.readouterr().out.strip().split("/login#")[1]
    assert (await browsers().post("/api/auth/login", json={"token": fresh})).status_code == 200


async def test_recording_an_inviter_ties_access_to_theirs(monkeypatch) -> None:
    host, _token = await _telegram_member("SetInviter-Host")
    async with SessionLocal() as db:
        legacy = User(first_name="SetInviter-Legacy")
        db.add(legacy)
        await db.commit()

    await invite.set_inviter(legacy.id, host.id)

    assert (await _verdict(legacy.id)).reason == "inviter"  # host is not on the list
    _allow(monkeypatch, host.telegram_id)
    assert (await _verdict(legacy.id)).allowed


async def test_recording_an_inviter_refuses_what_makes_no_sense() -> None:
    host, _token = await _telegram_member("Refuse-Host")
    root, _token = await _console_root("Refuse-Root")
    async with SessionLocal() as db:
        first, second = User(first_name="Refuse-A"), User(first_name="Refuse-B")
        db.add_all([first, second])
        await db.commit()
    await invite.set_inviter(second.id, first.id)

    for user_id, inviter_id, expected in [
        (first.id, first.id, "own inviter"),
        (first.id, second.id, "cycle"),
        (first.id, 999_999, "999999"),
        (host.id, root.id, "Telegram"),
        (root.id, first.id, "already has"),
        (second.id, root.id, "already has"),
    ]:
        with pytest.raises(SystemExit) as refused:
            await invite.set_inviter(user_id, inviter_id)
        assert expected in str(refused.value)


async def test_confirming_refuses_members_whose_origin_is_known() -> None:
    host, _token = await _telegram_member("Confirm-Host")
    root, _token = await _console_root("Confirm-Root")
    async with SessionLocal() as db:
        invited = User(first_name="Confirm-Invited", invited_by_id=root.id)
        db.add(invited)
        await db.commit()

    for user_id, expected in [
        (host.id, "Telegram"),
        (root.id, "already"),
        (invited.id, "invited by"),
    ]:
        with pytest.raises(SystemExit) as refused:
            await invite.confirm(user_id)
        assert expected in str(refused.value)


async def test_a_cycle_is_refused_not_followed_forever(caplog) -> None:
    async with SessionLocal() as db:
        first, second = User(first_name="Cycle-A"), User(first_name="Cycle-B")
        db.add_all([first, second])
        await db.flush()
        first.invited_by_id, second.invited_by_id = second.id, first.id
        await db.commit()

    with caplog.at_level(logging.WARNING, logger="app.membership"):
        assert (await _verdict(first.id)).reason == "invalid"
    assert "cycle" in caplog.text


async def test_a_missing_ancestor_is_refused() -> None:
    """Only possible with foreign keys off, which is how the table got damaged before."""
    async with SessionLocal() as db:
        orphan = User(first_name="Orphan")
        db.add(orphan)
        await db.commit()
    raw = sqlite3.connect(settings.database_url.split("///", 1)[1])
    raw.execute("UPDATE users SET invited_by_id = 999999 WHERE id = ?", (orphan.id,))
    raw.commit()
    raw.close()

    assert (await _verdict(orphan.id)).reason == "invalid"


async def test_a_chain_longer_than_any_family_is_refused() -> None:
    root, _token = await _console_root("Deep-Root")
    async with SessionLocal() as db:
        parent = root.id
        for depth in range(MAX_CHAIN):
            node = User(first_name=f"Deep-{depth}", invited_by_id=parent)
            db.add(node)
            await db.flush()
            parent = node.id
        await db.commit()

    assert (await _verdict(parent)).reason == "invalid"
    assert (await _verdict((await _row("Deep-3")).id)).allowed


@pytest.mark.parametrize(
    "damage", [{"console_root": True}, {"invited_by_id": "root"}], ids=["root", "invited"]
)
async def test_a_telegram_member_with_app_provenance_is_damaged(monkeypatch, damage) -> None:
    root, _token = await _console_root(f"Damaged-Root-{next(_ids)}")
    host, _token = await _telegram_member(f"Damaged-Host-{next(_ids)}")
    _allow(monkeypatch, host.telegram_id)
    values = {k: (root.id if v == "root" else v) for k, v in damage.items()}
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == host.id).values(**values))
        await db.commit()

    assert (await _verdict(host.id)).reason == "invalid"


async def test_a_root_that_also_has_an_inviter_is_damaged() -> None:
    root, _token = await _console_root("Both-Root")
    async with SessionLocal() as db:
        both = User(first_name="Both", console_root=True, invited_by_id=root.id)
        db.add(both)
        await db.commit()

    assert (await _verdict(both.id)).reason == "invalid"


# --- the operator's view -------------------------------------------------------


async def test_listing_says_who_gets_in_and_why_not(monkeypatch, capsys) -> None:
    host, _token = await _telegram_member("List-Host")
    root, _token = await _console_root("List-Root")
    async with SessionLocal() as db:
        db.add_all(
            [
                User(first_name="List-Invited", invited_by_id=root.id),
                User(first_name="List-Legacy"),
            ]
        )
        await db.commit()

    await invite.listing()
    lines = {
        line.split()[1]: line for line in capsys.readouterr().out.splitlines() if "List-" in line
    }

    assert "telegram" in lines["List-Host"] and "not in ALLOWED_TELEGRAM_IDS" in lines["List-Host"]
    assert "console root" in lines["List-Root"] and "allowed" in lines["List-Root"]
    assert f"invited by {root.id}" in lines["List-Invited"]
    assert "unconfirmed" in lines["List-Legacy"] and "REFUSED" in lines["List-Legacy"]
    assert host.id


# --- entry points that must not hand out what the chain refuses ----------------


async def test_no_link_for_someone_whose_inviter_lost_access(monkeypatch, browsers) -> None:
    host, token = await _telegram_member("NoLink-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)
    await _invite(hosting, "NoLink-Guest")
    _allow(monkeypatch)

    with pytest.raises(SystemExit) as refused:
        await invite.link((await _row("NoLink-Guest")).id)
    assert "inviter has no access" in str(refused.value)


async def test_restoring_does_not_mend_a_broken_chain(monkeypatch, browsers) -> None:
    host, token = await _telegram_member("Mend-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)
    guest = await _signed_in(browsers(), await _invite(hosting, "Mend-Guest"))
    # History keeps the row through the revocation, so there is something to restore.
    assert (await guest.post("/api/vouchers", json={"merchant": "Mend-Card"})).status_code == 201
    guest_row = await _row("Mend-Guest")
    await invite.revoke(guest_row.id)
    _allow(monkeypatch)

    await invite.restore(guest_row.id)

    assert (await _verdict(guest_row.id)).reason == "inviter"


async def test_confirming_a_revoked_member_leaves_them_revoked() -> None:
    async with SessionLocal() as db:
        legacy = User(first_name="Confirm-Revoked")
        db.add(legacy)
        await db.commit()
    await invite.revoke(legacy.id)  # no history, no invitees: the row goes
    async with SessionLocal() as db:
        assert await db.get(User, legacy.id) is None
        kept = User(first_name="Confirm-Revoked-Kept")
        db.add(kept)
        await db.flush()
        db.add(Voucher(merchant="Confirm-Revoked-Card", created_by_id=kept.id))
        await db.commit()
    await invite.revoke(kept.id)  # history: the row stays, revoked

    await invite.confirm(kept.id)

    assert (await _verdict(kept.id)).reason == "revoked"


async def test_a_refused_login_uses_the_link_up(monkeypatch, browsers) -> None:
    """Documented behaviour: the link is spent, no session is opened."""
    host, token = await _telegram_member("Spent-Host")
    _allow(monkeypatch, host.telegram_id)
    hosting = await _signed_in(browsers(), token)
    link = await _invite(hosting, "Spent-Guest")
    guest_row = await _row("Spent-Guest")
    _allow(monkeypatch)

    assert _refusal(await browsers().post("/api/auth/login", json={"token": link}), "inviter")
    assert await _credentials(guest_row.id) == (0, 1)
    async with SessionLocal() as db:
        row = (
            await db.execute(select(LoginToken).where(LoginToken.user_id == guest_row.id))
        ).scalar_one()
        assert row.used_at is not None

    _allow(monkeypatch, host.telegram_id)
    retry = await browsers().post("/api/auth/login", json={"token": link})
    assert retry.status_code == 401


async def test_the_mini_app_answers_to_the_allowlist_alone(monkeypatch, browsers) -> None:
    """initData is checked against ALLOWED_TELEGRAM_IDS, and a guest has no way in there."""
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    member_id = next(_ids)
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": member_id, "first_name": "MiniApp-Member"}),
    }
    header = {"Authorization": f"tma {sign(fields)}"}
    mini_app = browsers()

    assert (await mini_app.get("/api/me", headers=header)).status_code == 403
    _allow(monkeypatch, member_id)
    assert (await mini_app.get("/api/me", headers=header)).status_code == 200

    # A guest invited from the Mini App rests on that member, like any other.
    response = await mini_app.post(
        "/api/auth/invite", headers=header, json={"name": "MiniApp-Guest"}
    )
    guest = await _signed_in(browsers(), response.json()["url"].split("/login#")[1])
    _allow(monkeypatch)
    assert (await mini_app.get("/api/me", headers=header)).status_code == 403
    assert _refusal(await guest.get("/api/me"), "inviter")

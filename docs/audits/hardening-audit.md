# Hardening audit — Phase 1

Audited commit: `eaa294d` (main, 2026-10-25). Read-only phase: no source code, tests or
dependencies were changed. Every reproduction below ran against a throwaway SQLite database
in a temporary directory, with synthetic merchants (`SynthShop`, `SynthA`, …) and the
`DEV_MODE` header. Nothing touched a real `.env`, the production server or real card data.

Each finding is labelled with how sure it is:

- **Confirmed**: reproduced end to end, or the mechanism is fully visible in code with no
  runtime dependency.
- **Strongly supported**: the code path is clear, but the effect depends on a runtime
  (a browser, a production load) that was not exercised here.
- **Needs runtime verification**: plausible, not demonstrated.

---

## 1. Executive summary

No P0 was found. Every route under `/api` except images, barcodes, `/login` and the
DEV_MODE-gated routes requires an authenticated household member. The image and barcode
routes are capability URLs by design. Telegram `initData` verification uses aiogram's
`check_webapp_signature`, and there is no route that skips authentication.

The serious problems are about **integrity, not secrecy**, and an authenticated member (or
just a flaky network) can trigger them:

| # | Sev | Finding | Status |
|---|-----|---------|--------|
| F1 | P1 | Concurrent balance updates lose spends (5 × 10 € from 50 € leaves 20 €) | Confirmed |
| F2 | P1 | Pillow 12.3.0 (37 advisories, including heap overflows), and the decoder accepts any format | Confirmed (exposure), CVEs per advisory |
| F3 | P1 | Service worker serves a stale barcode for up to 180 days after the code is corrected | Strongly supported |
| F4 | P1 | A member can mint console members that outlive their own removal from `ALLOWED_TELEGRAM_IDS` | Confirmed |
| F5 | P2 | "Single-use" login link redeemable several times concurrently | Confirmed |
| F6 | P2 | `image_id` is not validated or exclusive; deleting one card deletes another card's screenshot | Confirmed |
| F7 | P2 | Negative/oversized amounts accepted; `PATCH balance_amount` bypasses the ledger | Confirmed |
| F8 | P2 | Image decoding: decompression bomb → 500; a 20 KB file costs ~220 MB RAM; decode blocks the event loop | Confirmed |
| F9 | P2 | Expiry reminder fires at most once per card, ever — a corrected date is never reminded | Confirmed |
| F10 | P2 | Rolling back the image past a migration crash-loops the app | Confirmed |
| F11 | P2 | PWA caches every card (codes, notes) for 7 days; no logout button; revoked device still shows codes offline | Strongly supported |
| F12 | P2 | Nightly backup (all codes + screenshots) goes unencrypted into the family group | Confirmed (documented trade-off) |
| F13–F22 | P3 | DEV_MODE guard, headers, transitions, token cleanup, logs, dev deps, backup FD leak, … | See §3 |

**Safest first fix:** F1 (atomic balance update). It is a few lines in one function, needs
no migration, changes no response shape, and it is the only finding that silently corrupts
the number the whole app exists to keep right. See §11.

---

## 2. Architecture and trust boundaries

```
 Telegram client ──initData (HMAC, 24h)──┐
 Browser PWA ──cookie gutschwein_session─┤
                                         ▼
 Caddy (TLS, headers) ──► uvicorn :8000 (127.0.0.1 only) ── FastAPI app
                                │   ├── /api/*            auth: get_current_user()
                                │   ├── /api/images/*     capability URL, no auth
                                │   ├── /api/barcodes/*   capability URL, no auth
                                │   └── /, /login, /demo  static SPA
                                ├── aiogram bot (polling) — allowlist per message
                                ├── background: reminders, digest, backup, maintenance
                                └── /data: SQLite (WAL) + uploads/  (uid 10001)
 Family Telegram group ◄── notifications, digest, reminders, nightly backup archive
```

Trust boundaries and who crosses them:

1. **Internet → API.** Identity is one of three things, checked in this order in
   `get_current_user()` ([auth.py:94](../../backend/app/auth.py#L94)):
   - `X-Dev-User` (only when `DEV_MODE=true`),
   - the session cookie (`resolve_session` + `check_allowed`),
   - `Authorization: tma <initData>` (HMAC with the bot token, age ≤ `INIT_DATA_MAX_AGE`,
     id in `ALLOWED_TELEGRAM_IDS`).
2. **Member → member.** There is none, by design: one household, every member reads and
   writes every card (`docs/internals.md`, "Access model"). Ownership is enforced only for
   deleting comments. So IDOR/BOLA in the usual sense does not apply. The relevant
   question is whether membership itself can be gained or kept improperly (F4, F5).
3. **Capability URLs.** `/api/images/<yyyy-mm>/<32 hex>.webp` and `/api/barcodes/<same>`
   need no auth. Their 128-bit names are the secret.
4. **Bot ↔ group chat.** Anything posted to `FAMILY_CHAT_ID` is readable by every member
   of that Telegram group, whether or not they are on the allowlist (F12).
5. **Server console.** `python -m app.invite` creates members with no Telegram id. Whoever
   has a shell is trusted.
6. **Client device.** Cache Storage (service worker) and the httpOnly cookie live on the
   phone/PC (F11).

---

## 3. Findings

### F1 — P1 — Concurrent balance updates lose spends · Confirmed

**Where.** [routers/vouchers.py:345-403](../../backend/app/routers/vouchers.py#L345-L403)

```python
voucher = await get_voucher_or_404(session, voucher_id)      # SELECT, no transaction yet
current = voucher.balance_amount if ... else voucher.value_amount
...
new_balance = current - payload.spent                         # computed in Python
voucher.balance_amount = new_balance                          # UPDATE … SET balance_amount=<constant>
record_event(..., {"spent": str(delta), "remaining": str(new_balance), ...})
await session.commit()
```

**Mechanism.** This is a read-modify-write with no lock and no version check. pysqlite only
emits `BEGIN` before the first DML, so the `SELECT` runs outside any transaction and holds
no snapshot. Two requests both read 50, both compute 40, and both write 40. The second
`UPDATE` simply waits out `busy_timeout` and succeeds. Each request also writes its own
`balance_updated` event, so **the event log and `balance_amount` disagree**: statistics
(summed from events) say more was spent than the balance reflects. `mark_used`
([:308-329](../../backend/app/routers/vouchers.py#L308-L329)) has the same pattern and can
write two `used` events and two zeroing spends.

**Reproduction (synthetic).** In-process ASGI client, `DEV_MODE=true`, temp DB:

```python
v = POST /api/vouchers {"merchant":"SynthShop","value_kind":"amount","value_amount":"50"}
await asyncio.gather(*[POST /api/vouchers/{v.id}/balance {"spent":"10"} for _ in range(5)])
```

Result: all five `200`, **final balance `20.00`**, 5 `balance_updated` events summing to
50. The card should be `0.00` and auto-marked `used`.

**Impact / prerequisites.** Any member. Concurrent requests come from two people paying at
once, or more commonly from one: a double tap the UI does not catch, a Telegram WebView
retry, or a client retry after a timeout whose request had in fact been applied. There is
no idempotency key, so a retried spend is applied twice. The result is a wrong balance at
the till, which is the core number of the app.

**Minimal fix.** Make the write conditional on what was read, and refuse instead of
overwriting:

```python
result = await session.execute(
    update(Voucher)
    .where(Voucher.id == voucher.id, Voucher.balance_amount.is_(current_as_stored))
    .values(balance_amount=new_balance, balance_uncertain=False)
)
if result.rowcount != 1:
    raise HTTPException(409, Message("error.balance_changed"))   # client reloads and retries
```

(For `balance_amount IS NULL`, the first spend on a card that only has `value_amount`, the
predicate is `IS NULL`.) An alternative with the same effect for every voucher write is
SQLAlchemy's `version_id_col` on `Voucher`, which turns the lost update into
`StaleDataError` → 409. That is a migration (one integer column), so it is the second step,
not the first.

**Regression tests.**
- Five concurrent `spent=10` on a 50 card: either the final balance is 0 and the five
  spends sum to 50, or the losers get 409. Never a 200 that is not reflected.
- The sum of `spent` in events equals `value_amount - balance_amount` after any sequence.
- Concurrent `/use` produces exactly one `used` event.

---

### F2 — P1 — Vulnerable Pillow decodes any format from member uploads · Confirmed exposure

**Where.** [constraints.txt:42](../../backend/constraints.txt#L42) `pillow==12.3.0`;
[storage.py:57](../../backend/app/storage.py#L57) and
[barcode.py:158](../../backend/app/barcode.py#L158) call `Image.open(io.BytesIO(data))`
with no `formats=` restriction. The only gate is the **client-declared** content type
([storage.py:88](../../backend/app/storage.py#L88)). The bot path
([bot.py:155-161](../../backend/app/bot.py#L155-L161)) accepts any document whose
client-declared MIME type starts with `image/`.

**Mechanism.** `pip-audit -r constraints.txt` reports 37 advisories against Pillow 12.3.0,
all fixed in 13.0.0. They include a heap buffer overflow *write* in the bundled libopenjp2
(GHSA-78g4-xqwv-q3g8), out-of-bounds reads and a heap overflow in the TIFF decoder
(CVE-2026-112896/112393/112404), and several memory-exhaustion and infinite-loop bugs (BMP
RLE, MSP, SPIDER bomb-check bypass, MIC, APNG). Because `Image.open` probes every
registered plugin, the format that gets decoded is whatever the bytes say, not what the
header claimed.

**Reproduction.** A TIFF file uploaded as `x.png` with `Content-Type: image/png` →
**200**, decoded and stored. (The CVEs themselves were not exploited; only the reachability
of the vulnerable decoders was shown.)

**Impact / prerequisites.** An authenticated member, a stolen session, or anyone who can
post an image document in a chat the bot reads as an allowlisted user. The worst case is
memory corruption inside the server process, which holds the bot token and the database.
The realistic case is a crash or OOM of the single container.

**Minimal fix.**
1. Bump to `pillow>=13.0.0` in `pyproject.toml`, run `make lock`, and rebuild.
2. Decode only what the product accepts:
   `Image.open(buf, formats=["JPEG", "PNG", "WEBP", "HEIF", "GIF"])` in both places. Drop
   TIFF/BMP from `LOSSLESS_SOURCES` unless they are really needed.

**Regression tests.** Uploading TIFF/BMP/JPEG 2000 bytes, with any declared type, returns
400 `error.image_unreadable`. A test asserts that the Pillow version in `constraints.txt`
is ≥ 13 (or a CI `pip-audit` step, see the plan).

---

### F3 — P1 — Stale barcode at the till after the code is corrected · Strongly supported

**Where.** [vite.config.ts:42-46](../../frontend/vite.config.ts#L42-L46) caches
`/api/(images|barcodes)/` **CacheFirst for 180 days**.
[api.ts:141](../../frontend/src/api.ts#L141) builds the barcode URL from the *image id
only*: `/api/barcodes/${imageId}`. The SVG is generated from `voucher.code` and
`voucher.barcode_format` ([routers/barcodes.py](../../backend/app/routers/barcodes.py)),
and both can change without the image changing: editing the code in the form, or
`app.rescan --apply`.

**Mechanism.** The comment in `vite.config.ts` says the names are content handles. That
holds for the image but not for the barcode: its URL stays the same while its content
changes. After the first view, the service worker never asks the network again, so the
corrected code is never drawn. The server's own `Cache-Control: max-age=3600` is ignored by
CacheFirst.

**Reproduction (browser, not run here).** Open a card with a decoded barcode in the
installed PWA. Edit the card's code. Reopen the scan screen: the SVG shows the old code.
DevTools → Application → Cache Storage → `gutschwein-cards` holds the old response.

**Impact.** The cashier scans the wrong number. This is exactly the case the redraw exists
for: the decoder misread the code, so the user corrected it. The PWA only; inside Telegram
it depends on whether the WebView keeps the service worker.

**Minimal fix.** Put the content into the URL: `barcodeUrl(imageId, code, format)` →
`/api/barcodes/${imageId}?v=${hash(code + format)}` (the server ignores the query).
Alternatively, move barcodes to `StaleWhileRevalidate`.

**Regression tests.** A unit test that `barcodeUrl` differs when the code differs. An e2e
test: edit the code, and the scan screen requests a new URL.

---

### F4 — P1 — In-app invites create members who outlive the inviter's revocation · Confirmed

**Where.** [routers/auth.py:148-180](../../backend/app/routers/auth.py#L148-L180) (any
member may `POST /api/auth/invite {"name": …}`, which creates a `User` with
`telegram_id=NULL`); [auth.py:75](../../backend/app/auth.py#L75) (`check_allowed`: a
console member is allowed while the row exists);
[invite.py:89-116](../../backend/app/invite.py#L89-L116) (`--revoke` refuses as soon as the
member has any history).

**Mechanism.** `CLAUDE.md` states: "Neither path may become a way around the other". The
in-app invite is exactly such a way around. Telegram member A, before being removed from
`ALLOWED_TELEGRAM_IDS`, invites "Grandma" and keeps the link (or redeems it in a second
browser). Removing A locks A out, but "Grandma's" session is a console member and stays
valid for 90 days. It can mint further sessions for itself (`invite` with no name), so in
practice it never expires.

**Reproduction.**
```text
POST /api/auth/invite  (as 1001)  {"name": "SynthGuest"}      → link
ALLOWED_TELEGRAM_IDS = "1000"                                 # 1001 removed
POST /api/auth/login {"token": <link token>}                  → 200, cookie
GET  /api/vouchers  (cookie)                                  → 200
```

**Impact / prerequisites.** A malicious or compromised member keeps permanent access after
removal. Mitigations that exist: the family chat is told about every invite (only if a bot
and `FAMILY_CHAT_ID` are configured; `notify()` swallows failures), and the session shows
up on *Access*. Revoking it there works only until the guest opens another session, and
there is no in-app way to remove the member.

**Minimal fix (pick one; product decision).**
- (a) Record `invited_by_id` on console members, and have `check_allowed` refuse a console
  member whose inviter is a Telegram member no longer on the allowlist. This needs a
  migration.
- (b) Restrict named invites to the console (`app.invite`) and keep in-app invites for "a
  second device for me" only. No migration, smallest change.
- In either case, add a "disabled" state, or let `--sessions-off` also block new logins,
  so a member with history can be locked out for good.

**Regression tests.** In `tests/test_invite.py`: a guest invited by a member who is then
removed gets 403 (option a) or cannot be created in-app (option b).

---

### F5 — P2 — A single-use login link can be redeemed several times · Confirmed

**Where.** [sessions.py:62-75](../../backend/app/sessions.py#L62-L75)

```python
row = (await session.execute(select(LoginToken).where(...))).scalar_one_or_none()
if row is None or row.used_at is not None or ...: return None
row.used_at = now            # UPDATE … WHERE id=?   (no "AND used_at IS NULL")
await session.commit()
```

**Reproduction.** `POST /api/auth/dev-token`, then five concurrent `POST /api/auth/login`
with the same token → `[200, 200, 200, 200, 200]`, which opens five sessions.

**Impact.** The single-use guarantee in `docs/internals.md` does not hold under
concurrency. Exploitation needs the token itself (a forwarded link, or a link preview bot
in a chat fetching `/login#…`; the fragment is not sent, so this is mostly theoretical).
Low practical risk, but it is the same pattern as F1, and the fix is the same idea.

**Minimal fix.** `UPDATE login_tokens SET used_at=:now WHERE token_hash=:h AND used_at IS
NULL AND expires_at > :now`, and continue only if `rowcount == 1`.

**Regression test.** Five concurrent redeems → exactly one 200, four 401.

---

### F6 — P2 — `image_id` is neither validated nor exclusive · Confirmed

**Where.** `_resolve_image` ([routers/vouchers.py:70-75](../../backend/app/routers/vouchers.py#L70-L75))
checks only `storage.absolute_path(image_id).is_file()`, which prevents traversal but does
not check the `IMAGE_ID_RE` pattern or whether another voucher already uses the file.
Deletion is per voucher: `delete_voucher` →
`storage.delete(image_path)` ([:471-478](../../backend/app/routers/vouchers.py#L471-L478)),
and `update_voucher` → `storage.delete(old)`, which runs **before** `commit()`
([:277](../../backend/app/routers/vouchers.py#L277) vs [:283](../../backend/app/routers/vouchers.py#L283)).

**Reproduction.**
- Upload one PNG; create `SynthA` and `SynthB` with the same `image_id`; delete `SynthB` →
  `SynthA` still references the id, `GET /api/images/<id>` → **404**. The screenshot (the
  card itself, for a barcode-only gift card) is gone.
- `image_id: "notes.txt"` (any file inside `uploads/`) → **201**. The voucher then points
  at a file that the image route refuses to serve, and the maintenance sweep, which keys
  on the pattern, would never collect it.

**Impact.** Data loss of a card's only picture, through an ordinary UI flow or a buggy
client. The `delete before commit` ordering also means a failed commit (e.g. `database is
locked` after 5 s) leaves the row pointing at a file that is already deleted.

**Minimal fix.** In `_resolve_image`: require `IMAGE_ID_RE.match`, and reject an id already
referenced by a *different* voucher (`409`). In `update_voucher`/`delete_voucher`: delete
the old file only after `commit()` succeeds.

**Regression tests.** Reusing another voucher's `image_id` → 409. A non-matching id → 400.
A forced commit failure leaves the old file in place.

---

### F7 — P2 — Amount validation and a ledger bypass · Confirmed

**Where.** [schemas.py:67](../../backend/app/schemas.py#L67) and
[:103](../../backend/app/schemas.py#L103) declare `value_amount: Decimal | None` with no
bounds; [schemas.py:110](../../backend/app/schemas.py#L110) has
`balance_amount: Decimal | None` on `VoucherUpdate`. `update_voucher` applies it with a
plain `setattr` ([routers/vouchers.py:256-259](../../backend/app/routers/vouchers.py#L256-L259)).

**Reproduction.**
- `PATCH {"value_kind":"amount","value_amount":"-5","balance_amount":"-99.999"}` → 200,
  value `-5.00`, balance **`-100.00`** (silently rounded), and the event log shows only
  `updated`, with **no `balance_updated`**.
- `POST /api/vouchers {"value_amount":"-20"}` → 201, balance `-20.00`.
- `value_amount: "123456789012345.678"` on a `Numeric(10,2)` column → 201, stored as
  `123456789012345.67`. SQLite enforces no precision. On Postgres (mentioned in `CLAUDE.md`
  as a possible move) the same request would be a 500.

**Impact.** Breaks the invariant in `CLAUDE.md` ("every change is an append-only
`balance_updated` event"): statistics and the card disagree, and an emptied balance via
PATCH does not mark the card `used`. Negative amounts corrupt the per-currency sums. The
frontend **never sends `balance_amount`** (grep of `frontend/src`), so this is unused API
surface.

**Minimal fix.** Remove `balance_amount` from `VoucherUpdate`, since balance changes go
through `/balance`. Add `Field(ge=0, max_digits=10, decimal_places=2)` to every money
field (`value_amount` in `VoucherFields`/`VoucherUpdate`, `spent`/`remaining` in
`BalanceUpdate`). `spent` with three decimals is currently quantized silently; rejecting
is more honest.

**Regression tests.** Negative, three-decimal and 11-digit amounts → 422. `PATCH
balance_amount` → ignored or 422, and the balance is unchanged.

---

### F8 — P2 — Image decoding: bombs, memory, and a blocked event loop · Confirmed

**Where.** `to_webp` ([storage.py:54-75](../../backend/app/storage.py#L54-L75)) catches
`UnidentifiedImageError, OSError, ValueError`, but **not** `PIL.Image.DecompressionBombError`
(a direct `Exception` subclass). `save_upload` → `save_bytes` → `to_webp` runs
**synchronously on the event loop** ([storage.py:87-101](../../backend/app/storage.py#L87-L101)).
There is no `Image.size` check before the full decode.

**Reproduction.**
- A 20000×20000 bilevel PNG (a few tens of KB) → unhandled `DecompressionBombError` → 500.
- A 13000×13000 bilevel PNG of **20 KB** → accepted. Measured peak RSS went from 183 MB to
  **404 MB** for one request. Pillow's default limit lets up to ~178 MP through, and a
  palette or RGB image converted to RGB costs 3 bytes/pixel (~500 MB).

**Impact.** A few such uploads in parallel OOM a 1 GB VPS (the deployment the docs
describe). During every decode, all other requests, the bot and the background loops are
stalled, because the work is not in a thread. The bot path has the same code and in
addition lets `HTTPException` escape a handler (no reply to the user).

**Minimal fix.** In `to_webp`: open, read `image.size`, and refuse above e.g. 40 MP
(`error.image_too_large`) *before* `exif_transpose`/`load`. Catch `DecompressionBombError`.
Call `save_bytes` via `asyncio.to_thread` from `save_upload` and from the bot.

**Regression tests.** A synthetic 20000×20000 PNG → 400 (not 500). A size-limit test. A
test that `save_upload` does not run the decode on the loop thread (patch `to_webp` to
assert `threading.current_thread() is not main`).

---

### F9 — P2 — An expiry reminder fires at most once per card, forever · Confirmed

**Where.** [bot.py:328](../../backend/app/bot.py#L328) selects
`Voucher.reminded_on.is_(None)`; [bot.py:309](../../backend/app/bot.py#L309) sets it to
*today*. Nothing ever clears it: not `PATCH valid_until`, not `restore`, not `unuse`. The
column comment in `models.py` says "Expiry date we already sent a reminder for", but it
stores the send date, not the expiry date.

**Reproduction.** A card expiring tomorrow → the reminder pass sends 1. PATCH
`valid_until` to +40 days, then later back to +2 days (simulating the new date
approaching) → the next pass sends **0**.

**Impact.** A card whose date was corrected (an estimated rule replaced by the printed date,
a renewed card) is never warned about again. This silently disables the app's core
promise for exactly the cards someone cared enough to fix.

**Minimal fix.** Compare against the date reminded for: store `reminded_on = valid_until`
and select `or_(reminded_on.is_(None), reminded_on != valid_until)`. No migration: same
column, new meaning, and existing rows simply get one more reminder at most.

**Regression test.** Remind, change `valid_until`, approach the new date → one new
reminder. An unchanged date → no repeat.

---

### F10 — P2 — Rolling back past a migration crash-loops the app · Confirmed

**Where.** `upgrade_database()` → `command.upgrade(cfg, "head")`
([migrations.py:56](../../backend/app/migrations.py#L56)), run in the lifespan. The
deploy guide sells rollback as "a tag" (`deploy <older-sha>`).

**Reproduction.** Upgrade a temp DB, then set `alembic_version` to a revision the code does
not know (what an older image sees after a newer one migrated) → `CommandError: Can't
locate revision identified by '0010_…'`. The lifespan fails, the container restarts, and
the same happens again.

**Impact.** The documented rollback path fails exactly when it is needed: after a release
that both migrated and broke something. There is also no snapshot taken before
migrating, so a bad data migration has only the last nightly backup (up to 24 h old) to go
back to.

**Minimal fix.** (1) Before `command.upgrade`, if the DB is not at head, write a
`sqlite3.backup` snapshot to `/data/pre-migration-<rev>.db` (reuse
`backup._snapshot_database`). (2) Document that a rollback across a migration needs
`alembic downgrade` from the *newer* image first, or a restore of that snapshot. (3)
Optionally, catch the unknown-revision case and fail with a message that says so.

**Regression test.** Startup on a DB with an unknown revision fails with the explicit
message. A pending migration leaves a snapshot file that passes `PRAGMA integrity_check`.

---

### F11 — P2 — Card data persists on the device; no logout · Strongly supported

**Where.** [vite.config.ts:50-60](../../frontend/vite.config.ts#L50-L60): every `GET
/api/*` is cached NetworkFirst in `gutschwein-api` for 7 days (60 entries), and that
includes `/api/vouchers` (codes, notes, conditions), `/api/me` and `/api/auth/sessions`.
Images and barcodes are cached for 180 days (F3). `api.logout` exists
([api.ts:68](../../frontend/src/api.ts#L68)), but **nothing calls it**: there is no logout
button anywhere in `src/`, although `docs/internals.md` says "logging out is a different
button". Nothing clears Cache Storage on logout or on a 401.

**Mechanism.** NetworkFirst falls back to the cache when the network fails or takes more
than 4 s. A lost phone whose session was revoked from another device still shows every
card, with codes, when opened offline or on a bad connection. On a shared computer, the
user cannot sign out at all, short of asking someone else to revoke the session.

**Verification needed.** In a browser: log in, browse, revoke the session from another
device, go offline, reload. The list is expected to render from `gutschwein-api`.

**Minimal fix.** Add the logout button (*Access* page), and make it call `api.logout()`,
then `caches.delete('gutschwein-api')` and `caches.delete('gutschwein-cards')`, then
reload. Do the same cache purge whenever any API call returns 401/403. Optionally, exclude
`/api/vouchers*` from runtime caching, or shorten it to hours.

**Regression tests.** An e2e test: logout → `caches.keys()` no longer contains either
cache, and `/api/me` is 401.

---

### F12 — P2 — Nightly backups expose every code to the whole group · Confirmed, documented

**Where.** [backup.py](../../backend/app/backup.py): `tar.gz` of the full DB and every
screenshot, sent with `send_document` to `FAMILY_CHAT_ID`. `docs/deploy.md` acknowledges
that codes end up on Telegram's servers.

**What is not documented.** The group's membership is not the allowlist. Anyone in the
group (a relative who was never given app access, a member later removed from
`ALLOWED_TELEGRAM_IDS`) can download any past archive and read every code, PIN (in
`notes`) and screenshot. Revoking someone from the app does not revoke their copies of the
backups.

**Minimal fix (product decision).** Either encrypt the archive (e.g. `age` with a
passphrase/recipient from `.env`, and the restore doc gains one command), or send backups to
a separate chat (`BACKUP_CHAT_ID`, defaulting to `FAMILY_CHAT_ID`), e.g. the owner's private
chat. At minimum, state this in `docs/deploy.md` next to the restore instructions.

**Regression test.** With an encryption key configured, the archive is not a readable
tarball and decrypts to one that is.

---

### P3 findings

**F13 — DEV_MODE is a full bypass, guarded only by an env flag.** Confirmed by reading.
With `DEV_MODE=true`, `X-Dev-User: <any int>` creates and returns that user **without the
allowlist check** ([auth.py:102-106](../../backend/app/auth.py#L102-L106)), and
`/api/auth/dev-token` ([routers/auth.py:183](../../backend/app/routers/auth.py#L183))
mints a login link for anyone. CI verifies that the image's default is off, but nothing
stops a production `.env` with `DEV_MODE=true` (copied from a dev `.env`). *Fix:* refuse to
start when `DEV_MODE` is on and `WEBAPP_URL` starts with `https://` (or `BOT_TOKEN` is
set), unless an explicit `DEV_MODE_I_KNOW=1` is also set. Log a loud warning in any case.
*Test:* settings with both values → startup error.

**F14 — The app sends no security headers of its own.** No CSP, no `frame-ancestors`, no
`X-Content-Type-Options`. They come only from the Caddyfile in `docs/deploy.md`, and the
nginx variant there lists none. *Fix:* a small middleware: `X-Content-Type-Options:
nosniff`, `Referrer-Policy: no-referrer`, and a CSP with `frame-ancestors
https://web.telegram.org https://*.telegram.org` (the Mini App must remain frameable by
Telegram Web). *Test:* `GET /` and `GET /api/me` carry the headers. Needs runtime
verification inside Telegram Web/Desktop before tightening the CSP.

**F15 — Status transitions have no preconditions.** Confirmed: `restore` on a **draft** →
200 `active`, which skips `activate_draft`'s notification. `unuse` on an active card, and
`archive`/`restore` from any state, all write events. Concurrent `/use` (F1) double-writes.
*Fix:* an allowed-transition table in `_transition()`, with 409 otherwise. *Test:* a
parametrized matrix of status × action.

**F16 — Locking someone out leaves their pending login links valid.** `revoke`/`--sessions-off`
([invite.py:113](../../backend/app/invite.py#L113), [:125](../../backend/app/invite.py#L125))
delete sessions but not unexpired `login_tokens`. That is a window of up to 10 minutes.
Also `POST /api/auth/sessions/others` from the Mini App (no cookie) deletes **every
household session**. That matches the design ("lost-phone button"), but it is worth one
line in the UI copy. *Fix:* delete the user's `LoginToken` rows alongside the sessions.
*Test:* after `--sessions-off`, a link issued a minute earlier → 401.

**F17 — Capability URLs and search terms reach the access logs.** uvicorn's access log
(container JSON logs) and Caddy's `log` record `/api/images/<id>` and
`/api/vouchers?q=<term>`, and a member may search by card number. The image ids are the
credential for those files. *Fix:* `--no-access-log` in uvicorn (Caddy already logs), and
document that the journal holds capability URLs. Needs runtime verification of the actual
Caddy log format.

**F18 — Runtime advisories outside Pillow.** `aiohttp 3.14.3` (8 advisories, fix 3.14.4),
`multidict 6.7.1` (fix 6.9.1), `certifi 2026.7.22` (distrusted root, fix 2026.10.19).
aiohttp is used only as aiogram's *client* to `api.telegram.org`; the server is uvicorn, so
the smuggling and parser advisories do not apply. Bump all of them in the same `make lock`
as F2.

**F19 — Dev-only npm advisories.** `npm audit`: 9 (5 high) in vite, esbuild, vitest,
`@vitest/mocker`, fast-uri, nanoid, source-map-js, brace-expansion, serialize-javascript.
`npm audit --omit=dev` → **0**. These matter for the dev server (`make dev-web` exposes the
Vite server; esbuild/vite path-traversal advisories), not for the shipped bundle. *Fix:*
`npm audit fix` regenerated with `npx npm@10 install` (see `CLAUDE.md`), separately from
any functional change.

**F20 — Backup: leaked connections and silently degraded archives.**
`with sqlite3.connect(...) as src, sqlite3.connect(...) as dst:`
([backup.py:43](../../backend/app/backup.py#L43)) commits on exit but **does not close**
either connection, so two file descriptors leak per backup until GC. Once DB + images
exceed 45 MB, *every* nightly archive drops all images
([backup.py:77](../../backend/app/backup.py#L77)), permanently, and only the caption says
so. *Fix:* `contextlib.closing(...)`. Split images into a second archive, or send only
images added since the last full one. *Test:* the snapshot leaves no open handle on the
source (count `/proc/self/fd` before and after).

**F21 — `--forwarded-allow-ips "*"`** ([Dockerfile:34](../../Dockerfile#L34)). This is safe
only because compose binds `127.0.0.1:8000`. Anyone running the image with `-p 8000:8000`
lets clients spoof `X-Forwarded-For`/`-Proto`. Nothing currently uses the client IP, so the
impact is small today. *Fix:* `--forwarded-allow-ips 127.0.0.1` (Caddy on the host
connects via loopback). Needs runtime verification with the actual proxy topology.

**F22 — A write on every Telegram-authenticated request.** `upsert_user`
([auth.py:58-72](../../backend/app/auth.py#L58-L72)) commits on every request (it updates
`last_seen_at`), turning reads into write transactions that compete for SQLite's single
writer lock. The same `LAST_USED_RESOLUTION` throttle used for sessions would remove it.
Two concurrent *first* requests from a new Telegram id can both `INSERT` and one gets an
`IntegrityError` → 500. Strongly supported, not reproduced.

### Checked and found sound

- **initData**: aiogram's `check_webapp_signature` (constant-time compare). Age is checked,
  `user` is required, and the allowlist is checked before `upsert_user`.
- **Session cookies**: 256-bit, stored as SHA-256, `HttpOnly; Secure; SameSite=Lax`.
  Expiry is checked on every use, and sessions are re-checked against membership on every
  request. CSRF: all state changes are non-GET, and the cookie is Lax. The Mini App uses a
  header, which cannot be sent cross-site without a CORS preflight. No CORS is configured
  in production.
- **Path traversal**: `storage.absolute_path` resolves and checks `is_relative_to`. The
  image and barcode routes also require `IMAGE_ID_RE`. The SPA fallback checks
  `is_relative_to(STATIC_DIR)`.
- **Barcode SVG**: zxing-cpp's writer emits no human-readable text. A code of
  `<script>…` yields no script in the SVG (tested for Code128, QR, Aztec, PDF417,
  DataMatrix).
- **Telegram HTML**: `html_t`/`group_t` escape every substituted value
  (`tests/test_chat_html.py`).
- **Container**: non-root uid 10001, the data volume only, the port bound to loopback, and
  `.env` excluded from the build context.
- **Logs**: no codes, tokens or initData are logged by the app.
- **Money in SQL sums**: `SUM(balance_amount)` on SQLite returned exact values at this
  scale (6 × 0.10/0.20 → `0.90`). SQLAlchemy quantizes on read.

---

## 4. Evidence summary

All file references are relative to the repository root at `eaa294d`. Line numbers are
given inline in each finding above. The reproduction scripts lived only in the session
scratchpad and are reproduced in shortened form in each finding. They used:

```python
os.environ.update(DATA_DIR=<tempdir>, DATABASE_URL="sqlite+aiosqlite:///<tempdir>/a.db",
                  DEV_MODE="true", RUN_BOT="false", ALLOWED_TELEGRAM_IDS="1000,1001",
                  BOT_TOKEN="", FAMILY_CHAT_ID="", WEBAPP_URL="https://example.invalid")
from app.main import app; from app.migrations import upgrade_database
upgrade_database()
client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
headers = {"X-Dev-User": "1000"}
```

Raw output of the main run:

```
1 concurrent spends: statuses [200, 200, 200, 200, 200] final balance 20.00 events 5 sum spent 50.0
2 concurrent redeem of one token: [200, 200, 200, 200, 200]
3 shared image_id: A still references True -> image GET 404
3b non-image file inside uploads accepted as image_id: 201
4 PATCH negative amounts: 200 -5.00 -100.00 events ['updated', 'created']
4b create with negative face value: 201 -20.00
4c create with 18-digit amount on Numeric(10,2): 201 123456789012345.67
5 20000x20000 PNG: unhandled exception -> DecompressionBombError
6 TIFF content labelled image/png: 200
7 restore on a draft: 200 active
8 guest invited by a since-removed member: login 200 -> list 200
B first pass sent 1 / after extending and approaching the new date, sent: 0
rollback start: CommandError Can't locate revision identified by '0010_from_a_newer_image'
to_webp(13000x13000 PNG, 20587 bytes): peak RSS 183 MB -> 404 MB
```

## 5–8. Reproduction, impact, fix, regression tests

These are given per finding in §3, to keep each one self-contained. The order of the fixes
is in [`hardening-plan.md`](hardening-plan.md).

## 9. Existing test and lint results

| Check | Command | Result |
|---|---|---|
| Backend lint | `ruff check app tests` | All checks passed |
| Backend tests | `python -m pytest -q` | **247 passed**, 1 warning (Starlette: `httpx` with TestClient deprecated) |
| Frontend types | `npm run typecheck` (`tsc --noEmit`) | Passed |
| Frontend unit | `npm run test:unit` (vitest) | **38 passed** (4 files) |
| Python deps | `pip-audit -r backend/constraints.txt` | pillow 37, aiohttp 8, multidict 1, certifi 1 |
| npm deps | `npm audit` / `--omit=dev` | 9 (dev only) / **0** |
| e2e (Playwright) | — | **Not run**: needs browsers and a running stack. |

Run on Python 3.14 with `constraints.txt` (CI uses 3.13), from a clean checkout of
`eaa294d` in a scratch worktree with `npx npm@10 ci`. `backend/.venv` and
`frontend/node_modules` do not exist in this checkout.

None of the existing tests covers concurrency, amount bounds, image-id reuse, the
reminder after a date change, or invite-after-revocation. That is why every finding above
passes CI.

## 10. Unverified assumptions and remaining risks

- **F3/F11 were not run in a browser.** The conclusions follow from the Workbox strategies
  as configured. Whether Telegram's WebView keeps a service worker between openings
  varies by platform.
- **The Pillow CVEs were not exploited.** Only the reachability of the TIFF decoder was
  shown, and JPEG 2000 reachability was inferred from `Image.open` without `formats=`.
  Severity follows the advisories.
- **Concurrency on the real server.** Reproduced in-process (one event loop, as in
  production with a single uvicorn worker). More workers would make F1/F5 more likely,
  not less.
- **Production configuration was not inspected.** Not seen: `.env`, the Caddyfile, the
  group's membership, or whether `FAMILY_CHAT_ID` is the group. F12–F14 and F17 depend on
  them.
- **The deploy script on the server** (`deploy <sha>`) is not in the repository, so F10's
  rollback path was reasoned from `docs/deploy.md`.
- **Not audited in depth:** `quickadd.py` parsing edge cases, `expiry.py` rules, the demo
  client (structurally isolated, and enforced by `e2e/demo.spec.ts`), Alembic revisions
  0001–0009 beyond their transactional setup, and the GitHub Actions supply chain
  (actions are pinned by major tag, not by SHA).
- **No rate limiting anywhere.** The tokens are 256-bit and initData is HMAC'd, so brute
  force is not a concern. An authenticated member can still flood uploads (see F8).
- **Orphan uploads:** the 24 h grace period plus F6's sharing means the sweep is correct
  only while no two vouchers share a file.

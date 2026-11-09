# Technical audit — November 2026

Audit only: no code, configuration, production data or remote state was changed. Every
reproduction ran against a throwaway SQLite database in a temporary directory with
synthetic cards (`Synth…`). Production was only *read*: container state, schema revision,
Caddy site list and `.env` flags, without printing hosts, ids or values. No card code,
token or personal datum appears below.

Follows [`hardening-audit.md`](hardening-audit.md) (October 2026, findings F1–F22). Where
an earlier finding is still open it keeps a reference to its old id.

## 1. Baseline

| | |
|---|---|
| Branch / commit | `main` @ `d9a72bcbc1f6`, clean, equal to `origin/main` |
| CI on that commit | green (backend, frontend, deploy script under dash, image smoke test, e2e) |
| Production | image `f35106f0d938` (25 Oct), schema **0010**, healthy, 0 restarts; **old** `/root/deploy.sh`; no snapshot directory |
| Not yet in production | migration 0011 (unique picture index), F10-a deploy script, the manual Deploy workflow (CI side only) |

**Architecture.** One container: FastAPI (`app.main`) serving the API and the built PWA,
the aiogram bot polling in the same process, and background loops (reminders, digest,
nightly backup — started by the bot; maintenance sweep — started by the app). SQLite in
WAL mode and `uploads/` on a bind mount; Caddy in front on loopback.

**Schema.** Alembic 0001→0011, linear. Upgrade head → downgrade base → upgrade head on
an empty database passes. Revisions run in the app's lifespan on every start.

**Auth model.** Telegram `initData` (HMAC, 24 h) for the Mini App; one-time links (256
bit, SHA-256 stored, 10 min, single use — atomic since F5) exchanged for a 90-day
`HttpOnly; Secure; SameSite=Lax` cookie for the PWA; membership re-checked on every
request through the invitation chain (F4). One household: every member may read and change
every card, by design.

**Images.** `uploads/<yyyy-mm>/<128-bit hex>.webp`, served without auth as capability URLs;
one card per picture (F6, index 0011); only the maintenance sweep deletes.

**Telegram.** Bot answers allowlisted users; notifications, weekly digest, expiry
reminders and the nightly backup go to `FAMILY_CHAT_ID`.

**Backups.** Nightly archive (SQLite backup API + all pictures) into the family chat;
server cron snapshots the database only. F10-a adds pre-deployment snapshots (not
installed).

**Checks run.**

| Check | Result |
|---|---|
| Backend pytest | 338 passed |
| Ruff (`app tests`, `deploy/`) | clean |
| Frontend `tsc --noEmit` | clean |
| Vitest | 38 passed |
| Production build (`vite build`) | ok |
| Deploy script tests (`deploy/`) | 40 passed (local `sh`; dash in CI) |
| Migrations up/down/up, empty DB | ok |
| Playwright e2e | **not run locally**: installed Chromium build (1254) does not match Playwright 1.62 (1234); not downloaded. Green in CI on the same commit |
| `pip-audit` (runtime pins) | Pillow 12.3.0: 39 advisories (fix 13.0.0); aiohttp 3.14.3: 8; certifi: 2; multidict: 1 |
| `npm audit --omit=dev` | 0 (15 in dev tooling only) |

No test failed before the audit.

**Fixed since October and present in production:** F1 (balance locking), F4 (invitation
chain), F5 (atomic login links), F6 (picture ownership), F7-part (PATCH cannot set the
balance). Fixed in code, not deployed: 0011, F10-a.

## 2. Findings

Severity: P0 active loss / exploitable secret exposure · P1 serious · P2 meaningful ·
P3 minor. Confidence: **confirmed** (reproduced or fully visible), **likely** (clear code
path, runtime not exercised), **needs verification**.

No P0 was found.

---

### T1 — P1 — Vulnerable image decoder reachable by any member · confirmed (exposure)
*Security / dependencies. Was F2.*

- **Where.** `backend/constraints.txt` pins `pillow==12.3.0`. `storage.py:58` and
  `barcode.py:158` call `Image.open(io.BytesIO(data))` with no `formats=`. The only gate is
  the client-declared content type (`storage.py:88-101`). The bot path takes any document
  whose declared MIME type starts with `image/` (`bot.py:155-161`).
- **Evidence.** `pip-audit`: 39 advisories against 12.3.0, including a heap-buffer-overflow
  write in the bundled libopenjp2 and out-of-bounds reads in the TIFF decoder. A TIFF sent
  as `image/png` is decoded and stored (`200`).
- **Impact.** An allowlisted member, a stolen session, or anyone who can make an allowlisted
  account send a document to the bot reaches decoders with known memory-corruption bugs in
  the process that holds the bot token and the database. Exploitation itself was not
  attempted.
- **Fix.** Pillow ≥ 13 (`make lock`). `Image.open(..., formats=["JPEG", "PNG", "WEBP",
  "HEIF", "GIF"])` in both places.
- **Test.** TIFF/BMP/JPEG 2000 bytes with any declared type → 400; HEIC still accepted.
- **Complexity.** S (plus a dependency upgrade to review).

### T2 — P1 — The next production deployment has no safe failure path · confirmed
*Reliability / deployment. Rest of F10.*

- **Where.** Server `/root/deploy.sh` (differs from `deploy/deploy.sh`); migrations in the
  lifespan (`main.py`, `migrations.py:56`).
- **Evidence.**
  - Production runs the old script: no lock, no pre-migration snapshot, no `:previous`.
    Only one gutschwein image is on the host, so a rollback needs the registry.
  - The next deployment carries migration 0011.
  - A revision that fails after its DDL leaves columns but no version stamp, and every start
    after that fails on `duplicate column name` (reproduced in October on 0010).
  - An older image refuses a newer schema (`Can't locate revision`).
- **Impact.** A failed start leaves the app down. If the database was touched, the only way
  back is the nightly backup (up to 24 h old) or a manual repair under pressure.
- **Fix.** Install `deploy/deploy.sh` (F10-a, done and tested) **before** deploying 0011,
  then run `dry-run`. No code change.
- **Test.** `dry-run` on the server; first deployment creates a snapshot and `:previous`.
- **Complexity.** S (operational).

### T3 — P2 — Same-site CSRF on body-less POST endpoints · confirmed
*Security / CSRF. New.*

- **Where.** No Origin or Fetch-Metadata check anywhere (`main.py`). The cookie is
  `SameSite=Lax` (`routers/auth.py`, `login`).
- **Evidence.**
  - All six Caddy sites on the server, Gutschwein included, share one registrable domain,
    so to a browser they are *same-site* and Lax sends the cookie with their POSTs.
  - With a foreign `Origin` and no body: `POST /api/vouchers/{id}/use` → 200 and the
    balance went to **0.00**; `POST /api/auth/sessions/others` → 204, every other device
    signed out.
  - JSON endpoints are safe: FastAPI answers 422 to `text/plain` and form bodies. DELETE
    needs a CORS preflight, which is refused.
- **Impact.** Needs script running on a sibling subdomain (an XSS or a compromise of one of
  the other five apps, several of them admin panels) and a member with a PWA browser
  session. The Mini App is not affected: it authenticates with a header. Possible actions:
  zero a card's balance, archive or reactivate cards, sign all devices out.
- **Fix.** A middleware that refuses non-GET/HEAD/OPTIONS requests whose `Origin` header is
  present and is not `WEBAPP_URL`'s origin (fallback: `Sec-Fetch-Site` ∉ {`same-origin`,
  `none`}).
- **Test.** Foreign Origin on `/use` → 403 and nothing changes; the app's own Origin → 200;
  no Origin (curl, bot) → allowed.
- **Complexity.** S.

### T4 — P2 — One tap on "used up" erases a gift card's balance, and undo does not bring it back · confirmed
*Data integrity / UX. New.*

- **Where.** `VoucherActions.tsx:30` (no confirmation). `routers/vouchers.py:384-400`:
  `/use` writes a `balance_updated` for the whole remainder and sets the balance to 0.
  `mark_unused` (`:530`) only changes the status.
- **Evidence.** A 50.00 card, 12.30 spent, then one tap on "used up": balance 0.00, the
  history shows a payment of 37.70. "Unuse": status active, balance **0.00**, a spend of 5
  refused with 400. Statistics keep the phantom 37.70 as spent.
- **Impact.** One mis-tap at the till hides the remaining money. It can be put back only by
  someone who reads the history and enters a correction.
- **Fix (decision).** Confirm "used up" when the balance is above 0. `/unuse` reverses the
  zeroing payment `/use` wrote (a new `balance_updated` with the negative amount, so history
  stays append-only).
- **Test.** use → unuse restores 37.70 and the events net to zero; the dialog appears only
  for a positive balance.
- **Complexity.** S–M (backend, frontend, demo client).

### T5 — P2 — Stale barcode at the till after a code is corrected · likely
*Frontend / PWA. Was F3.*

- **Where.** `vite.config.ts:42-46` caches `/api/(images|barcodes)/` CacheFirst for 180
  days. `api.ts:141`: the barcode URL is derived from the image id only, while the SVG is
  drawn from the card's code, which can change (form edit, `app.rescan`).
- **Impact.** After correcting a misread code, the installed PWA keeps drawing the old one.
  The cashier scans a wrong number and the payment fails.
- **Fix.** Put a short hash of `code + barcode_format` into the URL (`?v=`); mirror it in the
  demo client.
- **Test.** Unit: the URL changes with the code. e2e: editing the code requests a new URL.
- **Verification needed.** In a real browser and inside the Telegram WebView.
- **Complexity.** S.

### T6 — P2 — Card data and pictures outlive a session · likely
*Security / PWA. Was F11, plus pictures.*

- **Where.**
  - `vite.config.ts:50-60`: every `GET /api/*` is cached for 7 days, codes and notes
    included.
  - `api.logout` (`api.ts:68`) is never called: there is no logout button.
  - Nothing clears Cache Storage on 401/403.
  - Pictures and barcodes are capability URLs with no expiry (`routers/images.py:19-25`,
    `routers/barcodes.py:25`).
- **Impact.**
  - A revoked or lost device shows every card it has seen while offline.
  - A shared computer cannot be signed out.
  - A removed member can still open the pictures and barcodes of cards they had opened
    (not of new cards).
- **Fix.** Logout on *Access*, which also deletes both caches; the same purge on any
  401/403. Narrowing the API cache trades away offline use at the till — decision.
- **Test.** e2e: logout empties Cache Storage, and `/api/me` → 401.
- **Complexity.** S–M.

### T7 — P2 — An expiry reminder fires once per card, ever · confirmed
*Reliability / core feature. Was F9.*

- **Where.** `bot.py:328` selects `reminded_on IS NULL`; `bot.py:309` stores the send date.
  Nothing clears it.
- **Evidence.** Remind → change `valid_until` → the date approaches: 0 reminders.
- **Fix.** Store the reminded expiry date (`reminded_on = valid_until`) and select
  `reminded_on IS NULL OR reminded_on <> valid_until`. No migration.
- **Test.** Change the date → one new reminder; same date → none.
- **Complexity.** S.

### T8 — P2 — Image decoding can exhaust memory and blocks the server · confirmed
*Reliability / resource exhaustion. Was F8.*

- **Where.** `storage.py:55-76` catches `UnidentifiedImageError, OSError, ValueError` but
  not `DecompressionBombError`. `save_upload` → `save_bytes` decodes on the event loop
  (`:88-102`). The bot path has no size cap of its own (`bot.py:161`; Telegram allows up
  to 20 MB).
- **Evidence.** A 20000×20000 PNG → unhandled `DecompressionBombError` → 500. Measured in
  October: a 20 KB PNG under the bomb limit costs ~220 MB RSS.
- **Impact.** A few such uploads can run a small VPS out of memory. Every decode stalls all
  requests, the bot and the loops.
- **Fix.** Check `image.size` before decoding (e.g. 40 MP), catch the bomb error, decode in
  `asyncio.to_thread`, apply the same 12 MB cap in the bot.
- **Test.** The bomb → 400; the decode runs off the loop thread; the bot answers instead of
  failing.
- **Complexity.** S.

### T9 — P2 — Unbounded and negative amounts accepted · confirmed
*Data integrity. Rest of F7.*

- **Where.** `schemas.py:67`, `:103` (`value_amount` without bounds), `:153` (`spent` without
  `decimal_places`).
- **Evidence.**
  - Face value `-20` → 201 with balance −20.00.
  - A 15-digit amount on a `Numeric(10,2)` column → 201 (SQLite enforces nothing).
  - `spent: 0.004` → a recorded payment of 0.00 and a "balance corrected" notification.
- **Fix.** `Field(ge=0, max_digits=10, decimal_places=2)` on every money field; `spent`
  with `decimal_places=2`.
- **Test.** Negative, three-decimal and 11-digit values → 422.
- **Complexity.** S.

### T10 — P2 — Backups fail silently and are readable by the whole family group · confirmed
*Backup / reliability / confidentiality. Was F12, F20; partly new.*

- **Where.** `backup.py:129-145` (`backup_loop`), `:77`, `:43`; `bot.py:357-368`.
- **Evidence.**
  - One attempt a day at `BACKUP_HOUR_UTC`. A failure only reaches the log — no retry, no
    message to the chat. A host that is down at that hour skips the day.
  - Once the archive exceeds 45 MB, every archive drops all pictures; only the caption says
    so.
  - The loops are tasks of `run_bot`: if polling ends (a revoked token, say), backups and
    reminders stop with one log line.
  - Archives (every code and picture) go unencrypted to the family group, whose members are
    not the allowlist and keep old archives after removal.
  - The two `sqlite3` connections are not closed (`with` only commits).
- **Fix.** Retry within the day and post a short failure notice to the chat; start the loops
  independently of polling; close the connections; decide on encryption or a separate
  backup chat.
- **Test.** A failing `send_document` → retried, then one notice; polling crash → backups
  continue; snapshot leaves no open file descriptors.
- **Verification needed.** Membership of the family group.
- **Complexity.** M.

### P3 findings

| ID | Category | Where | Finding | Confidence |
|---|---|---|---|---|
| T11 | Security | `auth.py:104`, `routers/auth.py:192` | `DEV_MODE` bypasses allowlist and chain entirely; guarded only by the env flag (production: off, checked). Fix: refuse to start with `DEV_MODE` and an https `WEBAPP_URL`. (F13) | confirmed |
| T12 | Integrity | `routers/vouchers.py:530-550` | Transitions without preconditions: `restore` on a draft → 200 active, skipping `activate`'s checks and notice. (F15) | confirmed |
| T13 | Security | `main.py` | No CSP / `frame-ancestors` / `nosniff` from the app; HSTS and nosniff come only from Caddy. (F14) | confirmed |
| T14 | Security | `Dockerfile:34` | Access logs record picture capability URLs and search terms; `--forwarded-allow-ips "*"` is safe only while the port stays on loopback. (F17, F21) | confirmed |
| T15 | Performance | `auth.py:58-72` | Every Mini App request commits `last_seen_at` — a write lock on read paths; two first requests of a new id can race on insert. (F22) | likely |
| T16 | Correctness | `format.ts:62-71`, `models.py` (`is_expired`) | Date-only strings parsed as UTC (one day early west of UTC); "expired" uses the server's UTC date. No effect in CET/MSK. | confirmed |
| T17 | Dependencies | `constraints.txt` | aiohttp/multidict/certifi advisories (aiohttp is only the bot's client); 15 npm advisories in dev tooling only. | confirmed |
| T18 | Maintainability | `CLAUDE.md:107`, `docs/deploy.md:25`, `deploy/deploy.sh` | CLAUDE.md says "no invites" (they exist); deploy.md installs to `/root/gutschwein`, `deploy.sh` defaults to `/root/sparschwein`. | confirmed |
| T19 | Hygiene | git history, `.github/workflows` | An early commit of `.claude/settings.local.json` contains one IP address (no secrets); actions are pinned by major tag, not SHA. | confirmed |

### Checked and found sound

- **initData.** Constant-time HMAC, age limit, allowlist before upsert.
- **Login links.** 256 bit, hashed, 10 min. Concurrent redemption yields exactly one
  session; consumption and session creation are one transaction.
- **Membership chain.** Revocation, cycles, missing ancestors, depth, unknown origin all
  refused. Covered by 23 tests.
- **Balance.** Payments, `/use`, face-value edits and bot captions all write under the
  writer lock; history matches the balance under concurrency.
- **Pictures.** One owner per file (app check + index 0011); nothing but the sweep deletes;
  the sweep is serialised with attachments.
- **Path traversal and XSS.**
  - Traversal: refused on image, barcode and SPA routes.
  - Barcode SVG: carries no text.
  - Telegram HTML: escaped.
  - Frontend: no `dangerouslySetInnerHTML`.
- **CORS.** Not configured in production; DELETE and JSON bodies need a preflight that
  fails.
- **Repository secrets.** No secrets in the repository or its history (only placeholders and
  the test token).
- **CI.** CI and the deployment are separated: a push cannot deploy; Deploy requires a green
  CI run on `main`, a published image and the `production` environment.
- **Container.** Non-root uid 10001, port bound to loopback.
- **Double submission.** Payment, save, comment and status buttons are disabled while their
  request is in flight; deleting a card asks for confirmation.

## 3. What could not be verified

- **Playwright e2e locally** (browser build mismatch). They pass in CI on the audited commit.
- **The F10-a script with a real Docker daemon.** It is tested with a stub; never run on
  the host.
- **Service worker behaviour** (T5, T6) in real browsers and in Telegram's WebView.
- **Exploitability of the Pillow advisories** (only reachability shown).
- **Membership of the family Telegram group, and the bot's privacy mode** — this would need
  the bot token.
- **The full Caddy header configuration** for the Gutschwein site; how long Telegram keeps
  archives.
- **PostgreSQL** (not a supported target).

# Remediation plan — November 2026

For the findings in [`technical-audit-2026-11.md`](technical-audit-2026-11.md). Each batch
is one commit (or one operational step), testable on its own, and deployable through the
Deploy workflow. Order follows the priorities: losing or exposing cards, balance
correctness, backups, stability, frontend, maintainability.

| # | Batch | Findings | Kind | Migration |
|---|---|---|---|---|
| 0 | Install the F10-a deploy script, then deploy `HEAD` | T2 | operational | 0011 (already written) |
| 1 | Image decoding: Pillow 13, format allowlist, size cap, off-loop decode | T1, T8 | backend + deps | no |
| 2 | Origin check for state-changing requests | T3 | backend | no |
| 3 | Balance safety: confirm "used up", undo restores, amount bounds | T4, T9 | backend + frontend + demo | no |
| 4 | Reminders that follow the date | T7 | backend | no |
| 5 | Backups: retry, failure notice, independent loops, closed connections | T10 | backend | no |
| 6 | Till and device hygiene: barcode cache key, logout, cache purge | T5, T6 | frontend + demo | no |
| 7 | Small hardening | T11–T16, T18 | mixed | no |

---

## Batch 0 — Make the next deployment recoverable (T2)

- **Scope.** Copy `deploy/deploy.sh` to `/root/deploy.sh` on the server, run `dry-run`,
  then run the Deploy workflow with `HEAD`. This carries 0011, whose duplicate precondition
  held in the November audit — re-check it first.
- **Dependencies.** None. Must precede every other deployment.
- **Tests.**
  - `dry-run` output: no in-progress note, `.env` present.
  - After deploying: a complete snapshot in `/root/gutschwein-snapshots`; `:previous` =
    `f35106f0d938`; `alembic_version` = 0011; `/healthz` and the GET smoke checks.
- **Deployment risk.** First real use of the new script on the real Docker: `compose ps -q`,
  `inspect … Health` and pruning are untested against it.
- **Rollback.** The snapshot plus `:previous`, by hand (`docs/deploy.md`). 0011 → 0010 is
  `DROP INDEX`.

## Batch 1 — Image decoding (T1, T8)

- **Scope.**
  - `pillow>=13` + `make lock`;
  - `formats=[…]` in `storage.to_webp` and `barcode.decode`;
  - pixel cap before decode;
  - catch `DecompressionBombError`;
  - `asyncio.to_thread` for `save_bytes` (API and bot);
  - 12 MB cap in the bot.
- **Tests.**
  - TIFF/BMP/JP2 → 400; HEIC → 200;
  - 20000² PNG → 400;
  - decode not on the loop thread;
  - bot replies to an oversized or unreadable image;
  - existing barcode fixtures still decode.
- **Deployment risk.** A major Pillow version; `pillow_heif` compatibility; `Image.LANCZOS`.
  CI's image smoke test catches import errors.
- **Rollback.** Redeploy `:previous` (no schema change).

## Batch 2 — Origin check (T3)

- **Scope.** A middleware: for non-safe methods, a present `Origin` must equal `WEBAPP_URL`'s
  origin, else 403. `WEBAPP_URL` unset (development) disables the check.
- **Tests.**
  - Foreign Origin on `/use`, `/auth/sessions/others`, `/uploads` → 403 and nothing changes;
  - the app's Origin → OK;
  - no Origin (curl, bot) → OK;
  - Mini App requests carry the app's Origin.
- **Deployment risk.** A client sending an unexpected Origin, e.g. a Telegram client that
  serves the Mini App from another host. Check the Origin of real Mini App requests in the
  access log before enabling it.
- **Rollback.** `:previous`.

## Batch 3 — Balance safety (T4, T9) — **needs a product decision**

- **Scope.**
  - The frontend asks before "used up" when the balance is above 0; the demo client mirrors
    it.
  - `/unuse` reverses the payment `/use` wrote (a new `balance_updated` with a negative
    `spent`), restoring the balance.
  - Money fields: `ge=0`, `max_digits=10`, `decimal_places=2`.
- **Tests.**
  - use → unuse returns the exact remainder, and history nets to zero;
  - unuse of a card emptied by payments (not by `/use`) changes no balance;
  - bounds → 422;
  - e2e: the confirmation appears only with money left.
- **Deployment risk.** None for data. Existing negative or oversized rows stay readable
  (validation applies to input only).
- **Rollback.** `:previous`.

## Batch 4 — Reminders (T7)

- **Scope.** `reminded_on` stores the expiry date it reminded for. The query also matches
  `reminded_on <> valid_until`. Update the model's comment.
- **Tests.** Date changed → one new reminder; unchanged → none; existing rows remind at most
  once more.
- **Deployment risk.** At most one extra reminder per already-reminded card, once.
- **Rollback.** `:previous`.

## Batch 5 — Backups (T10)

- **Scope.**
  - Retry a failed nightly backup a few times within the day.
  - After the last failure, post one short notice to the family chat (no archive).
  - Start backup, digest and reminder loops from the app's lifespan, not from `run_bot`, so
    a polling failure cannot stop them.
  - `contextlib.closing` on both SQLite connections.
  - A caption warning that is hard to miss when pictures were dropped.
- **Decision.** Encrypt archives (`age`, key in `.env`) or send them to a separate backup
  chat. Not part of this batch until decided.
- **Tests.**
  - failing `send_document` → retries, then one notice;
  - polling task crash → the backup loop still runs;
  - no file descriptor left open after a snapshot.
- **Deployment risk.** Loop start order changes; duplicate loops must not run (one process).
- **Rollback.** `:previous`.

## Batch 6 — Till and device hygiene (T5, T6) — **needs a decision on offline caching**

- **Scope.**
  - `barcodeUrl(imageId, code, format)` with a short hash; the same in the demo client.
  - A logout button on *Access* (PWA only): `api.logout()`, then delete `gutschwein-api` and
    `gutschwein-cards`, then reload.
  - The same purge on any 401/403.
- **Tests.**
  - Unit: the URL changes with the code.
  - e2e: logout empties Cache Storage, and the next `/api/me` → 401.
  - A manual check in Telegram's WebView.
- **Deployment risk.** The service worker updates on the next visit; old cache entries age
  out.
- **Rollback.** `:previous`.

## Batch 7 — Small hardening (T11–T16, T18)

One commit each, each with its own test:
- **T11.** Refuse to start with `DEV_MODE` and an https `WEBAPP_URL`.
- **T12.** An allowed-transition table in `_transition()` → 409 otherwise; the UI only offers
  allowed actions.
- **T13.** `nosniff` and a CSP with `frame-ancestors` for Telegram's web clients — verify in
  Telegram Web and Desktop first.
- **T14.** `--no-access-log`, `--forwarded-allow-ips 127.0.0.1`.
- **T15.** Write `last_seen_at` at most every 15 minutes; re-select after an insert race.
- **T16.** Parse date-only strings as local dates in `formatDate`.
- **T18.** Fix CLAUDE.md and the install path in `deploy.md`.

T17 (dependency advisories outside Pillow) rides with batch 1's `make lock`. T19 needs no
code: the leaked value is an IP address already in DNS.

## Rollback in general

No batch except 0 changes the schema, so every rollback is the Deploy workflow (or
`deploy <tag>`) with the previous commit. With the F10-a script installed, `:previous` is on
the host and a snapshot exists for every deployment. Nothing is rolled back or restored
automatically.

# Hardening plan

Derived from [`hardening-audit.md`](hardening-audit.md) (finding ids F1–F22). Each step is
one commit. It can be tested on its own, and it changes nothing outside its scope. Each
step ships with the regression test named in the audit: write the test first and watch it
fail on the current code.

Order: data corruption first, then the attack surface reachable by any member, then
access-model gaps, then reliability and hygiene. Steps that need a product decision are
marked **decision**, and none of them blocks the steps before it.

## Wave 1 — stop silent data corruption (no migrations, no API shape changes)

| Step | Finding | Change | Test | Risk |
|---|---|---|---|---|
| 1 | F1 | `update_balance`: conditional `UPDATE … WHERE id=? AND balance_amount IS ?` and 409 on `rowcount != 1`. Same for the zeroing in `mark_used`. New key `error.balance_changed` (ru/en/de). | 5 concurrent spends → balances and event sums agree. Concurrent `/use` → one `used` event. | Low. A client that receives 409 shows the existing error toast, and the user retries. |
| 2 | F5 | `redeem_login_token`: conditional `UPDATE login_tokens SET used_at … WHERE used_at IS NULL AND expires_at > now`, checking `rowcount`. | 5 concurrent redeems → one 200. | Low. |
| 3 | F7 | Remove `balance_amount` from `VoucherUpdate`. Add `ge=0, max_digits=10, decimal_places=2` to the money fields. | Negative, 3-decimal and 11-digit amounts → 422. PATCH `balance_amount` is ignored. | Low. The frontend never sends it. Check `src/demo/api.ts` still type-checks. |
| 4 | F6 | `_resolve_image`: require `IMAGE_ID_RE`, and 409 if another voucher already references the id. Move `storage.delete(old)` after `commit()` in `update_voucher`. | Reuse → 409. A bad id → 400. A commit failure keeps the old file. | Low. Check whether any existing row shares a path first: `SELECT image_path, count(*) FROM vouchers GROUP BY 1 HAVING count(*)>1`. |
| 5 | F9 | Store `reminded_on = valid_until`. Select `reminded_on IS NULL OR reminded_on != valid_until`. Update the column comment. | Change the date → one new reminder. An unchanged date → none. | At most one extra reminder per already-reminded card, once. |

## Wave 2 — attack surface any member can reach

| Step | Finding | Change | Test | Risk |
|---|---|---|---|---|
| 6 | F2, F18 | `pillow>=13`, bump aiohttp/multidict/certifi. `make lock`, rebuild. Nothing else in this commit. | The full suite, plus a barcode decode on the existing fixtures (`test_barcode.py`). | Medium: a major Pillow version. Watch `pillow_heif` compatibility and the `Image.LANCZOS` alias. |
| 7 | F2 | `Image.open(..., formats=[…])` in `storage.to_webp` and `barcode.decode`. Trim `LOSSLESS_SOURCES`. | TIFF/BMP/JP2 bytes → 400 whatever the declared type. HEIC still accepted. | Low. Confirm with the family that nobody sends TIFF/BMP. |
| 8 | F8 | Pixel cap before decode (e.g. 40 MP), catch `DecompressionBombError`, run `save_bytes` in `asyncio.to_thread` (API and bot). The bot catches `HTTPException` from storage and answers with its message. | A 20000² PNG → 400. The decode runs off the loop thread. The bot replies to an unreadable image. | Low. |

## Wave 3 — the access model (**decision** needed first)

| Step | Finding | Change | Test | Risk |
|---|---|---|---|---|
| 9 | F4 | **Decision**: (a) `invited_by_id` + inviter check in `check_allowed` (migration), or (b) named invites console-only. Recommend (b) now, and (a) later if in-app invites are wanted. | A guest of a removed member → 403, or the in-app named invite → 403/absent. | (b) removes a UI feature. That needs `AccessPage` + i18n + demo client changes, and the e2e test for invites. |
| 10 | F16 | `revoke`/`--sessions-off` also delete the user's unexpired `LoginToken`s. | A link issued before `--sessions-off` → 401. | Low. |
| 11 | F13 | Refuse to start with `DEV_MODE=true` and an `https://` `WEBAPP_URL` (or a `BOT_TOKEN`) unless `DEV_MODE_ALLOW_PUBLIC=1`. | A settings combination → `RuntimeError`. | Check that the Playwright `webServer` env and `make dev-api` are unaffected (both use http). |

## Wave 4 — client-side data and the till screen

| Step | Finding | Change | Test | Risk |
|---|---|---|---|---|
| 12 | F3 | `barcodeUrl(imageId, code, format)` adds `?v=<short hash>`. The callers pass the voucher. Mirror it in the demo client. | A unit test: the URL changes with the code. e2e: editing the code requests a new URL. | Low. Old cache entries simply age out. |
| 13 | F11 | Logout button on *Access*: `api.logout()` → delete `gutschwein-api` and `gutschwein-cards` → reload. The same purge on any 401/403 from `request()`. Demo client: a no-op logout. i18n keys. | e2e: logout empties Cache Storage and `/api/me` → 401. | Low. Watch the Telegram WebView: no cookie there, so hide the button inside Telegram. |
| 14 | F11 | (Optional, **decision**) Exclude `/api/vouchers*` from runtime caching, or cap it at a few hours. | The config test, or manual offline behaviour. | Trades away offline access at the till. Decide together with the family. |

## Wave 5 — reliability and operations

| Step | Finding | Change | Test | Risk |
|---|---|---|---|---|
| 15 | F10 | A pre-migration snapshot (`backup._snapshot_database`) when the DB is behind head. A clear error on an unknown revision. `docs/deploy.md`: how to roll back across a migration. | An unknown revision → explicit error. A pending migration → a snapshot exists and passes `integrity_check`. | Disk: one DB copy per migration. Clean up snapshots older than N. |
| 16 | F20 | `contextlib.closing` around both sqlite3 connections in the backup. | No fd leak across a snapshot. | None. |
| 17 | F20 | (**decision**) When over 45 MB, send images in a second archive (or incrementally) instead of dropping them. | Archive building with a fake large upload dir. | Telegram limits. Two messages per night. |
| 18 | F12 | (**decision**) `BACKUP_CHAT_ID` and/or `age` encryption of the archive. Update the restore section. | An encrypted archive round-trips. | Losing the key means losing the backups. Document key custody. |
| 19 | F15 | An allowed-transition table in `_transition()`, 409 otherwise. | A status × action matrix. | Check every UI button only offers allowed actions (`VoucherActions.tsx`) and the demo client mirrors the rules. |
| 20 | F22 | Throttle `upsert_user` writes (`last_seen_at` resolution, write only on change). Handle the first-request `IntegrityError` by re-selecting. | Two concurrent first requests → both 200. A repeat request → no write. | Low. |

## Wave 6 — hygiene

| Step | Finding | Change | Test |
|---|---|---|---|
| 21 | F14 | Security-header middleware (nosniff, referrer policy, CSP `frame-ancestors` for Telegram). Verify in Telegram Web/Desktop/iOS/Android before enabling the CSP. | A header test on `/` and `/api/me`. |
| 22 | F17, F21 | `--no-access-log` and `--forwarded-allow-ips 127.0.0.1` in the Dockerfile. Verify that the proxy reaches the app via loopback. | The CI smoke test still passes. |
| 23 | F19 | `npm audit fix` via `npx npm@10 install` (full install, per `CLAUDE.md`). Nothing else in the commit. | CI (all three node jobs and the Docker image). |
| 24 | F2, F18, F19 | Add `pip-audit -r constraints.txt` and `npm audit --omit=dev` to CI, so the next Pillow-class problem fails a build instead of waiting for an audit. | CI itself. |

## Not planned

Rate limiting and per-member permissions are out of scope: the product is one trusted
household, and the tokens are unguessable. Revisit them if the access model changes.

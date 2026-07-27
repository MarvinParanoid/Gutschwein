# How it is put together

The decisions that are not obvious from the code, and the reasons behind them.

## Demo mode

`https://<domain>/demo` is the same app on made-up cards. The link is safe to hand to
anyone: no account, and everything works — spend, comment, add, delete. The lock screen
that greets any uninvited visitor offers the same button.

The isolation is structural rather than a matter of permissions: in demo mode the HTTP
client is swapped for `frontend/src/demo/api.ts`, which answers from an object in the tab
and **makes no requests at all** — there is nothing to authorise. `e2e/demo.spec.ts`
watches every request the page makes and fails if one reaches `/api`.

That client reimplements the server's rules — spending writes an event, an empty card
closes itself, statistics are summed from the log — so a visitor tries the real behaviour,
not a set of screens. The data lives in the tab and is gone when it closes; card pictures
are drawn in the browser (`demo/assets.ts`) to keep other people's logos out of the
repository.

`make demo-gif` re-records the README animation from the same dataset, in every language
(`docs/demo.gif`, `docs/demo-de.gif`). The recording script reads its button labels from
the dictionaries, so a renamed string breaks the recording instead of silently filming the
wrong screen.

## Languages

English, German and Russian, with no switch by design: the language comes from wherever
the app is open — `initDataUnsafe.user.language_code` in Telegram, `navigator.language` in
the PWA. Anything else falls back to `DEFAULT_LANGUAGE`.

- `frontend/src/i18n/ru.ts` is the source of truth; `en.ts` and `de.ts` are typed as
  `Dictionary = typeof ru`, so a forgotten key is a compile error rather than a blank.
- API errors are raised as a **key** (`Message("error.…")`) and rendered once at the
  boundary by the handlers in `main.py`, from `Accept-Language`. No helper has to carry a
  language through, and `tests/test_i18n.py` fails if a key is missing in any language or
  if the placeholders disagree between them.
- The bot answers in the language of whoever wrote to it, and stores it on the user so
  background jobs know it without an incoming message. The family chat has no single
  reader, so its messages use `DEFAULT_LANGUAGE`.

## Shop tiles

The square in front of a card carries the shop's colours and two or three letters, never the
voucher photo — a barcode screenshot is unreadable at 56px and looks the same on every card.

What the tile should match is the **card in your hand, not the logo on a white page**: the
two often differ. Douglas is the example — a black wordmark on a mint card, so the tile is
mint. Colours were taken from the cards where one was available and from brand references
otherwise; the ones still resting on a reference alone are MediaMarkt, Saturn, OBI, Louis,
Google Play, Wolt and the German grocers. Correct any of them freely: `brands.test.ts`
checks every pair for 4.5:1 contrast, so the only way to get it wrong is to make it
unreadable, and that fails the build.

Two colours are deliberately not the brand's own, because theirs cannot be read at this
size: Decathlon's `#0082c3` is darkened, and Airbnb's coral keeps its hue but takes dark
letters instead of white (white on it is 3.05:1).

## Access model

One shared household: everyone sees and edits every card. There are no groups or roles — a
deliberate omission.

Two kinds of member, and `check_allowed()` re-checks on every request rather than only at
login:

- a **Telegram member** is in exactly while their id is in `ALLOWED_TELEGRAM_IDS`, so
  removing it locks them out on the next request, including an already-open browser;
- a **console member** has no Telegram id at all (`python -m app.invite`), and for them the
  row is the membership — revoking deletes their sessions first, then the row.

Neither path may become a way around the other; `tests/test_invite.py` asserts that.

Sessions are visible and revocable from *Access* in the app: the household sees every
signed-in browser, not only its own, because the point is to notice a device that should
not be there. The browser making the request cannot revoke itself from that list — logging
out is a different button, and a screen that signs you out of itself reads as a crash.

The PWA has no `initData`, so it uses a one-time link — from the bot's `/login` or from the
console — exchanged for an httpOnly, Secure, SameSite=Lax cookie. Tokens are stored as
SHA-256 digests and die on first use, and they travel in the URL fragment, which browsers
never send to a server: not to the access log, not in a Referer.

Images are served from capability URLs — `/api/images/<yyyy-mm>/<32 hex>.webp` with no
authorisation, because `<img src>` cannot send headers. The filename is 128 bits of
randomness, unguessable and never listed, and a link can simply be forwarded into the
chat. If that ever stops being acceptable, serve them through `fetch` and a blob URL.

## Things worth knowing before changing something

- `settings` is a module-level singleton built at import time; tests set the environment in
  `tests/conftest.py` before importing anything from `app`.
- Migrations run inside the app's lifespan through `asyncio.to_thread`, because Alembic is
  sync. A schema change means a new revision — there is no `create_all` fallback.
- Status changes go through `_transition()` in `routers/vouchers.py`, which also writes the
  event. Nothing sets `voucher.status` directly.
- The gift-card balance lives in `vouchers.balance_amount`; every change is an append-only
  `balance_updated` event carrying `{spent, remaining, note}`. There is no ledger table, so
  corrections are ordinary updates and past events are never rewritten.
- Uploads are two-step: `POST /api/uploads` returns an `image_id`, then the card is created
  or patched with it. An abandoned form leaves an orphan file until the maintenance loop
  collects it.

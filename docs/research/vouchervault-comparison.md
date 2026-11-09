# VoucherVault and Gutschwein — a comparison

Research only, 2026-11-09. Nothing here is implemented. VoucherVault is GPL-3.0; no code
of it was copied into Gutschwein, and none should be — what is worth taking is ideas.

**Studied:** [l4rm4nd/VoucherVault](https://github.com/l4rm4nd/VoucherVault) at
[`7046266`](https://github.com/l4rm4nd/VoucherVault/tree/7046266) (v1.31.0, released the
same day), its README, wiki links, three screenshots, changelog, all 149 issues and the
`deeplink/` worker. Links to its source point at that commit, so line numbers stay true.
Gutschwein at `865419d` (production).

**Method:** the source was read, not the README believed. Where the two disagree, the
source wins and the difference is called out.

---

## 1. VoucherVault in one page

A Django 5 server-rendered app (~2,200 lines of Python, Bootstrap "NiceAdmin" template),
Celery + Redis for the daily expiry check, SQLite or PostgreSQL. Started 2024-07, 515 stars,
one maintainer, very responsive (most issues closed within days, 31 minor releases).

| Area | What the code actually does |
|---|---|
| **Model** | One `Item` per card: `type` (voucher, gift card, coupon, loyalty card), `redeem_code`, `code_type` (symbology), `pin`, `issuer`, `issue_date`, **`expiry_date` (required)**, `value` + `value_type` (money, percentage, multiplier), `currency`, one `file`, `tile_color`, `is_pinned`, `url`, `logo_slug`. UUID keys. [`models.py#L71-L111`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/models.py#L71-L111) |
| **No expiry** | The form fills an empty date with *now + 50 years* ([`forms.py#L80-L84`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/forms.py#L80-L84)); the maintainer disliked the idea ([#16](https://github.com/l4rm4nd/VoucherVault/issues/16)). |
| **Balance** | A separate `Transaction` table; balance = `value + sum(transactions)`, computed on read ([`views.py#L298-L299`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L299-L300)). A negative result is refused in the form. Reaching zero sets `is_used`. |
| **History** | Transactions can be **deleted** and their **dates edited** ([`views.py#L504-L529`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L504-L529)): the history is a scratch pad, not a record. |
| **Mark used / undo** | "Mark used" adds a transaction for the remainder; undoing deletes every transaction whose description equals the *translated* text "Marked as used, removing remaining value" ([`views.py#L564-L591`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L564-L591)) — switch the UI language in between and the undo silently does not find it. |
| **Codes** | Barcode or QR **generated on the server from the typed code** (treepoem/qrcode), stored as base64 PNG on the item and inlined into the page; regenerated when code or type changes ([`views.py#L398-L433`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L398-L433)). A valid EAN-13 is detected automatically. Fullscreen view, white quiet zone ([#134](https://github.com/l4rm4nd/VoucherVault/issues/134)), forced light background in dark mode ([#131](https://github.com/l4rm4nd/VoucherVault/issues/131)). |
| **Scanning** | Client-side ZXing in the browser: camera or an image file, with symbology detection ([`scanner.js`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/static/assets/js/scanner.js), [#108](https://github.com/l4rm4nd/VoucherVault/issues/108)). |
| **Files** | One image or PDF per item, served **behind login and an access check** ([`views.py#L531-L562`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L531-L562)) — no capability URLs. Replacing a file deletes the old one inside the request. |
| **Users and sharing** | Django users; owner-only edits; per-item sharing with other users. A recipient can view but **cannot add transactions** ([#50](https://github.com/l4rm4nd/VoucherVault/issues/50), [`views.py#L302-L304`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L302-L304)). Expiry notices go to the owner only. |
| **Auth** | Username/password (admin password in the container log), optional OIDC SSO. Sessions 30 minutes by default and end with the browser ([`settings.py#L59-L62`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myproject/settings.py#L59-L62)). CSP with `frame-ancestors 'none'`. |
| **Notifications** | Apprise (any of ~100 services), daily Celery task, a first notice at 30 days and a last one at 7 ([`check_expiration.py`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/management/commands/check_expiration.py)). |
| **Offline/PWA** | A 520-line hand-written service worker; a **manual** "Cache for offline" button that caches pages for 48 h **cache-first** ([`serviceworker.js#L8`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/serviceworker.js#L8), [`#L246-L285`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/serviceworker.js#L246-L285)). |
| **Organisation** | Search as you type, status and type filters, sort by expiry/name/date/value, pin to top, compact view, tile colours, duplicate item, dashboard with totals and a chart. |
| **Currencies** | 33 fixed codes. The dashboard sums one currency directly and converts mixed ones through **fixer.io** with a per-user API key; the stats API just adds them up ([#135](https://github.com/l4rm4nd/VoucherVault/issues/135)). |
| **Integrations** | A stats endpoint for Home Assistant behind one global bearer token; a public Cloudflare worker that turns `#name=…&code=…` links into a prefilled "create" form on your own instance ([`deeplink/`](https://github.com/l4rm4nd/VoucherVault/tree/7046266/deeplink), [#125](https://github.com/l4rm4nd/VoucherVault/issues/125)). |
| **Logos** | `img.logo.dev/<domain>?token=pk_…` fetched **by the browser** on every list view, with a token committed in the templates ([`inventory.html#L742`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/templates/inventory.html#L742), [`settings.py#L95`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myproject/settings.py#L95)). |
| **Backup/export** | None in the app: "back up the volume", or `manage.py dumpdata` from the wiki ([#83](https://github.com/l4rm4nd/VoucherVault/issues/83)). |
| **Deployment** | Docker Hub image, compose with Redis, Unraid template; four languages. |

**README versus code.** The claims hold, with three qualifications: "offline mode" is a
manual 48-hour snapshot, not offline-first; "multi-currency support" is conversion through
a paid-tier-limited third-party API, and the API total is wrong for mixed currencies;
"item sharing" is read-only for the recipient.

Screenshots: [dashboard](https://github.com/l4rm4nd/VoucherVault/blob/7046266/screenshots/dashboard.png),
[inventory](https://github.com/l4rm4nd/VoucherVault/blob/7046266/screenshots/items.png),
[item details](https://github.com/l4rm4nd/VoucherVault/blob/7046266/screenshots/item-details.png).

---

## 2. Feature matrix

✓ implemented · ◐ partial or with a caveat · — absent

| Capability | VoucherVault | Gutschwein | Note |
|---|---|---|---|
| Gift cards with a balance | ✓ derived from transactions | ✓ stored, every change an append-only event | see §4 |
| Percentage coupons, "other" offers | ✓ (+ multiplier) | ✓ | |
| Loyalty cards (code only, no value) | ✓ own type | ◐ `other` without a value; works only if a picture carries the barcode | |
| Card without an expiry | ◐ faked as +50 years | ✓ `null`, plus shop rules that *estimate* a date and say so | Gutschwein better |
| Expiry estimated from the shop's rule (§199 BGB) | — | ✓ | unique |
| "Balance uncertain" flag | — | ✓ | unique |
| Transaction history | ◐ editable and deletable | ✓ append-only, corrections are new events | Gutschwein better |
| Mark used / undo | ◐ undo by matching translated text | ✓ exact undo recorded in the event, reversed pairs excluded from statistics | Gutschwein better |
| Concurrent payments | ✓ by construction (sum of rows) | ✓ by locking | different, both sound |
| Barcode from a **typed** code | ✓ many symbologies, QR, EAN-13 auto | — only from a decoded picture | **gap** |
| Barcode from a picture | ✓ client-side ZXing | ✓ server-side zxing-cpp, with frame/panel handling | |
| Camera scanning in the app | ✓ | ◐ the PWA's file input opens the camera; decoding on upload | small gap |
| Fullscreen till view | ✓ | ✓ white, zoom, rotate, photo/code toggle | |
| Separate PIN field | ✓ masked, copy button | — (notes) | **gap** |
| Stale barcode after an edit | ✓ cannot happen (inlined) | ✓ versioned URL, server-checked | |
| Attachments | ◐ one file, image or PDF | ◐ one picture, one owner | |
| Picture access control | ✓ login + access check | ◐ capability URL, valid after logout | VoucherVault better |
| Users | ✓ independent accounts + admin | one household | different on purpose |
| Sharing | ◐ per item, read-only recipient | ✓ the whole household, everyone can spend | |
| Who spent what | — | ✓ events with actor, per-member statistics | unique |
| Comments on a card | — | ✓ | unique |
| Capture without opening the app | ◐ deep-link worker | ✓ forward a screenshot or "Rewe 50" to the bot | unique |
| Reminders | ✓ Apprise, 30 + 7 days, owner only | ✓ Telegram family chat, 3 days, follows the current date | see §4 |
| Weekly digest | — | ✓ | unique |
| Per-currency totals | ◐ conversion via fixer.io; API wrong (#135) | ✓ never added, never converted | Gutschwein better |
| Statistics | ◐ counts and a donut chart | ✓ spent by month, shop, member, per currency | |
| Search, filters | ✓ search, status, type | ✓ search, status, shop chips by use | |
| Sort, pin, compact view | ✓ | — sorted by soonest expiry | gap, minor |
| Duplicate a card | ✓ | — | gap, minor |
| Colours / logos | ◐ logo.dev (third party), tile colours | ✓ brand colours and initials, logos as local files | |
| Offline | ◐ manual 48 h, cache-first even online | ✓ automatic; network first; per-version barcodes | Gutschwein better |
| Sign-out clears the device | — (#119) | ✓ caches and HTTP cache, purge on confirmed loss of access | Gutschwein better |
| Backups | — (volume, `dumpdata`) | ✓ verified local + chat copy, reported failures | Gutschwein better |
| Export / import | ◐ `dumpdata` only | ◐ backup archive only | gap in both |
| Demo without an account | — | ✓ | |
| Languages | EN DE FR IT | RU DE EN, manual override | |
| SSO / OIDC | ✓ | — | |
| PostgreSQL | ✓ | — | |
| Home Assistant / API | ✓ stats endpoint | — | |
| CSP | ✓ | — (T13 in the audit) | VoucherVault better |

---

## 3. UX

**What works in VoucherVault** (from the screenshots and the issues people filed):
- The item page puts **code, copy button and PIN** in one block beside the details, and the
  barcode is one tap from fullscreen ([#99](https://github.com/l4rm4nd/VoucherVault/issues/99), [#89](https://github.com/l4rm4nd/VoucherVault/issues/89)).
- **Pin to top** ([#88](https://github.com/l4rm4nd/VoucherVault/issues/88)) and **duplicate** ([#69](https://github.com/l4rm4nd/VoucherVault/issues/69)) were requested by users and kept.
- Filter chips with counts (Available 4 · Expiring soon 4 · Used 1 · Expired 9).
- Typing a code produces a scannable barcode at once — the manual path is never second-class.

**What does not:**
- It is a desktop admin template: a sidebar, breadcrumbs ("Home / Inventory / Item
  Details"), five equal-weight buttons (Edit, Duplicate, Share, Mark used, Delete). On a
  phone at a till, that is scrolling and aiming.
- The dashboard leads with counts and a donut chart — information about the collection, not
  about the next action. The total is shown without a currency.
- The create form asks for type, issuer, name, code, symbology, issue date, expiry, value,
  value type, currency, colour, logo slug, URL, PIN, description and a file. Optional, but
  all on screen.
- A required expiry date made people invent dates ([#16](https://github.com/l4rm4nd/VoucherVault/issues/16), [#31](https://github.com/l4rm4nd/VoucherVault/issues/31)).
- Offline is a button the user must remember to press; logout reloads the page first to work
  around a stale CSRF token ([`base.html#L408-L440`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/templates/base.html#L408-L440)).

**Reducing manual entry:** VoucherVault's answer is scanning in the form and deep links.
Gutschwein's is not opening the form at all: a screenshot to the bot becomes a card with
its code decoded and a draft to complete. That is the stronger answer for gift cards that
arrive as images in messengers and email.

**Ideas for Gutschwein's list and card page:**
1. A barcode for typed codes (the biggest gap, §6).
2. A till shortcut on the list: cards with a barcode get a small "show code" target, so the
   most common action skips the card page.
3. PIN next to the code, masked, with copy.
4. "One more like this" on the card page.
5. Keep the list sorted by urgency; do not add sort settings — a pin, if anything.

---

## 4. Security and architecture lessons

**Offline data and logout — issue [#119](https://github.com/l4rm4nd/VoucherVault/issues/119), open.**
With the offline cache on, a second user in the same browser could get the first user's
pages back from the cache, and logout failed with a stale CSRF token. The maintainer's
position: a shared browser is a shared risk; per-user caches are "tricky". The code
confirms that logout never clears the caches; only a separate "Purge cache" link does.
**Gutschwein already did what #119 asks for** (T6): sign-out deletes the caches and asks for
`Clear-Site-Data: "cache"`; a server-confirmed loss of access purges as well, while an
expired Telegram initData does not. The lesson is to keep it that way: any new cached
resource must be added to `SENSITIVE_CACHES`.

**Cache invalidation — [#120](https://github.com/l4rm4nd/VoucherVault/issues/120), [#146](https://github.com/l4rm4nd/VoucherVault/issues/146).**
Cache-first pages for 48 hours mean an edit made on another device is not shown even
online, and a cached form posts a stale CSRF token (an iPhone upload failed that way). The
time-based scheme kept producing bugs. Gutschwein's choice — network first for data,
cache-first only for content-addressed or versioned resources — avoids the whole class.

**Mixed currencies — issue [#135](https://github.com/l4rm4nd/VoucherVault/issues/135), open.**
The stats API adds amounts of different currencies; the fix being discussed needs a fixer.io
key and the question of *whose* key. Gutschwein's rule (never add, never convert; a gift
card is only spendable at its shop) needs no key, no network and no exchange rate that is
wrong by the time it is shown. Keep it.

**Transaction consistency.** VoucherVault's ledger model is good: the balance is a sum of
rows, so two concurrent payments cannot overwrite each other. But the rows are mutable, and
the "used" undo matches translated text. Gutschwein's append-only events plus locks are the
stricter version; nothing to take over beyond the observation that a derived balance would
have avoided the locking work.

**Pictures.** VoucherVault serves files behind login and an ownership check; Gutschwein
serves capability URLs, valid after logout. That is the one place VoucherVault is
structurally better. Moving to authenticated `fetch` + blob URLs would close it, at the cost
of the browser HTTP cache doing less of the offline work. Not urgent for one household; worth
it before more external users.

**Notifications.** VoucherVault marks items as notified *before* sending and ignores the
result of `notify()`, and the flags never reset when the date changes — the two defects
Gutschwein fixed (F-series, T7). Lesson confirmed, nothing to import.

**Third parties.** `logo.dev` receives the shop list of every vault and the viewer's IP on
every list view, with a token in public templates. Gutschwein's "No merchant logos" and the
build-time logo folder are the private alternative; issue
[Gutschwein#2](https://github.com/MarvinParanoid/Gutschwein/issues/2) asks for logos — the
answer should stay local files, possibly uploadable at runtime.

**Backup and restore.** VoucherVault has none in the app. Gutschwein's verified local copy
plus chat copy is a real differentiator for people who are not sysadmins.

**API.** One global token for the stats API across all users. A dead view
([`views.py#L783-L788`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L783-L788))
would return every user's codes and PINs; it is not routed. If Gutschwein ever adds an API
for Home Assistant, it should be per-member tokens and aggregates only.

**Headers.** VoucherVault sets a CSP and `frame-ancestors`; Gutschwein does not yet (T13).

---

## 5. Product questions

**1. Why choose Gutschwein?** Because it is built for one household spending shared gift
cards, not for one person cataloguing items. Everyone can pay with any card and it is
recorded who did; the family chat is told what is expiring and what was spent; a
screenshot in Telegram is enough to add a card; the balance history cannot be rewritten;
estimated expiry dates for cards that print none; backups that are checked and reported;
and the device forgets the cards when signed out.

**2. What does VoucherVault do significantly better?** Codes typed by hand become scannable
barcodes (and QR codes); a PIN field; generic notification channels (Apprise) for people
without Telegram; independent user accounts and SSO; authenticated picture access; a CSP.

**3. Missing features that would change everyday use:** a barcode for typed codes (loyalty
cards and codes from emails are typed, and without it the till screen shows nothing); a PIN
field; a one-tap path from the list to the till view. Everything else is marginal.

**4. What to avoid deliberately:** currency conversion; per-item sharing and roles; a
configurable dashboard; manual offline modes; third-party logo services; transaction
editing; Celery/Redis-style infrastructure.

**5. Is Bitrefill integration a differentiator?** Not a meaningful one now. Bitrefill's
Personal API ([docs](https://docs.bitrefill.com/), [gift cards](https://docs.bitrefill.com/docs/gift-cards))
is for *buying* gift cards, paid in crypto, with an account-bound API key. Gutschwein's job
is the cards a family already *has* — mostly gifts. An integration would add a money flow,
a credential that can spend, and a vendor dependency, for a use the household does not have.
A card bought on Bitrefill can already be added by forwarding its screenshot or code to the
bot; that generic path covers it.

**6. Is Telegram-first capture a differentiator?** Yes — the strongest one. Gift cards arrive
as images and messages; forwarding one is less work than any form, and the decoded code,
estimated expiry and draft completion are already there. VoucherVault's closest answer
(deep links through a public worker) needs someone to *craft* a link. The risk is depending
on one messenger; the PWA has to remain complete without it (it is, except reminders).

**7. Gift cards only, or coupons and loyalty cards?** Stay gift-card focused — that is where
balance, history, expiry rules and reminders matter. Support coupons as now, and loyalty
cards only as "a code to show at the till": that needs a barcode from a typed code, not a
new type, points or programmes.

---

## 6. Recommendations

### Top 5 — high impact, low complexity

| # | Recommendation | User problem | Evidence | Benefit | Complexity | Security / privacy | Priority |
|---|---|---|---|---|---|---|---|
| 1 | **Barcode from a typed code**: choose the symbology (EAN-13 detected from its checksum, Code 128, QR) when there is no picture or it was unreadable | A loyalty card or an emailed code, typed in, shows nothing to scan at the till | VV generates from the typed code ([`views.py#L410-L431`](https://github.com/l4rm4nd/VoucherVault/blob/7046266/myapp/views.py#L410-L431)), [#49](https://github.com/l4rm4nd/VoucherVault/issues/49) (8 comments); Gutschwein draws only after decoding a picture (`services.apply_barcode`) and needs an image for the barcode address (`routers/barcodes.py`) | Every card with a code works at the till, also loyalty cards | S–M: `barcode_format` exists, `barcode.to_svg` exists; needs a writable format (validated list), and a barcode address for cards without a picture | The address is a capability URL; for picture-less cards derive it from the card id plus a random handle, never from the code | **P1** |
| 2 | **Till shortcut from the list** for cards with a barcode | Paying means: open list, find card, open card, tap picture — at the counter | VV [#89](https://github.com/l4rm4nd/VoucherVault/issues/89), [#99](https://github.com/l4rm4nd/VoucherVault/issues/99); Gutschwein reaches `ScanOverlay` only from `VoucherPage` | One tap less at the most time-critical moment | S, frontend + demo | none | **P1** |
| 3 | **PIN field**, masked, copy button, shown beside the code | Many gift cards have a PIN, today kept in notes, visible to anyone glancing at the screen | VV `pin` + "Hide PIN" (screenshot), [#129](https://github.com/l4rm4nd/VoucherVault/issues/129), [#130](https://github.com/l4rm4nd/VoucherVault/issues/130) | Online redemption without hunting in notes; less shoulder-surfing | S, but a **migration** (nullable column) — needs approval | Same sensitivity as the code; included in backups like the code; never in notifications | **P2** |
| 4 | **"One more like this"** (duplicate without picture, code or history) | Several identical coupons are entered one by one | VV [#69](https://github.com/l4rm4nd/VoucherVault/issues/69), [#126](https://github.com/l4rm4nd/VoucherVault/issues/126), [#143](https://github.com/l4rm4nd/VoucherVault/issues/143) (bugs from copying too much) | Faster entry | S, frontend + demo | Must not copy the picture (one owner per picture) or the code | **P3** |
| 5 | **Export** of cards and history as JSON/CSV, for members, never cached | "Can I get my data out?" — portability and trust, also for leaving | VV [#83](https://github.com/l4rm4nd/VoucherVault/issues/83) ended in `dumpdata`; Gutschwein has only the backup archive | Confidence for new self-hosters | S–M | Contains every code: authenticated, Origin-checked, `Cache-Control: no-store`, excluded from the service worker, an event in the history | **P3** |

### Top 3 strategic differentiators

1. **Capture by forwarding.** Extend what already works: forwarded e-mails or PDFs as well
   as screenshots, and "add as draft" for anything the bot cannot read. Evidence: the bot
   flow in `app/bot.py` and `app/quickadd.py`; VoucherVault needs a form or a crafted link.
2. **A shared household wallet with accountability.** Everyone can spend; the record says
   who; the chat hears about it; the digest closes the week. VoucherVault's sharing is
   read-only for recipients (#50) and its notices go to the owner only.
3. **Money you can trust at the till.** Append-only history, exact undo, per-currency truth,
   versioned barcodes, verified backups, sign-out that forgets. Every one of these is an
   open or past VoucherVault issue (#119, #120, #135, #146, transaction deletion). Say it in
   the README — it is invisible otherwise.

### Top 5 not worth implementing now

| Feature | Why not |
|---|---|
| **Bitrefill integration** | Buying, not keeping; a spending credential and a vendor in the core for no household need (§5.5). |
| **Currency conversion** | A rate is wrong by the time it is read, needs a third-party key (#135), and a gift card cannot be spent in another currency anyway. |
| **Per-item sharing, roles, independent accounts** | The household model is the product; per-item ACLs multiply every query and test. Revisit only if external users ask. |
| **Third-party logo service** | Leaks the shop list and IP on every view (VoucherVault ships a token for it). Local files already work; runtime upload is the private next step for Gutschwein#2. |
| **Configurable list (sort settings, compact mode, field toggles)** | VoucherVault grew a preferences page for it (#85: 10 comments). One good order (soonest expiry) beats a settings screen; a pin, if needed later. |

Also not now: OIDC, PostgreSQL, a Home Assistant API, a manual offline mode.

### Roadmap

**Stage 1 — the till (no migration).**
Barcode from a typed code (P1), till shortcut from the list (P1). Close the manual checks
of the last release (sign-out over https, barcode after an edit inside Telegram). Exit: every
card with a code can be shown at the till in two taps.

**Stage 2 — the card itself (one migration, needs approval).**
PIN field (P2), "one more like this" (P3), export (P3). Exit: nothing about a card lives in
the notes field by necessity.

**Stage 3 — beyond Telegram, and hardening.**
Reminders for PWA-only installs (Web Push, or Apprise if a dependency is acceptable);
authenticated picture access instead of capability URLs; CSP (T13); runtime-uploaded shop
logos (Gutschwein#2); the backup confidentiality decision (separate chat or encryption). Exit:
an install without Telegram is a complete product, and nothing sensitive is reachable by URL
alone.

---

## Recommendation

**Prioritise the VoucherVault-inspired till improvements, not Bitrefill.** The largest
everyday gap is that a typed code produces no barcode; it is small to close and benefits
every card. Bitrefill would add purchasing, payments and a spending credential to an app
whose value is keeping the cards a family already has — and cards bought there can already
be added through the bot. Revisit Bitrefill only if buying gift cards becomes a household
habit and someone asks for it.

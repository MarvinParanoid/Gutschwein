<img src="frontend/public/icon-192.png" alt="" width="88">

# Gutschwein

[![CI](https://github.com/MarvinParanoid/Gutschwein/actions/workflows/ci.yml/badge.svg)](https://github.com/MarvinParanoid/Gutschwein/actions/workflows/ci.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Image](https://img.shields.io/badge/ghcr.io-gutschwein-2496ed?logo=docker&logoColor=white)](https://github.com/MarvinParanoid/Gutschwein/pkgs/container/gutschwein)

A family gift-card manager: what is left on each card, who spent what, and a screen the
cashier can scan. Runs as a Telegram Mini App and as an installable PWA.

*Gutschein* (voucher) + *Schwein* (pig) — the piggy bank you keep your vouchers in.

<img src="docs/demo.gif" alt="Finding a card, showing it at the till, writing down what is left" width="300">

**[Try the demo](https://gutschwein.duckdns.org/demo)** — made-up cards, no account, nothing saved.

## Run it yourself

No Telegram account, no bot, no configuration — the demo dataset is enough to see every
screen:

```bash
git clone https://github.com/MarvinParanoid/Gutschwein && cd Gutschwein
cp .env.example .env
docker compose pull && docker compose up -d
# then open http://localhost:8000/demo
```

That pulls the published image (`ghcr.io/marvinparanoid/gutschwein`), so nothing is built
locally. Swap the last line for `docker compose up -d --build` to build from the checkout.

For a real installation you need a bot token and a public HTTPS domain: see
[docs/deploy.md](docs/deploy.md). It can also run [without Telegram
entirely](docs/deploy.md#members-without-telegram), with login links handed out from the
server console.

## The flow it is built around

A gift card with money on it gets spent over several trips:

1. open the app, find the shop (list or search);
2. tap the picture — it fills the screen on white, and the cashier scans it;
3. tap *Update balance* and type either what you paid or what the receipt says is left.

When the balance hits zero the card moves itself to *Spent*. Every payment lands in the
card's history: who, how much, when, and what for.

## What it does

- **Lists** by tab: active (soonest expiry first), drafts, spent, archive
- **Balance** with *spent* / *remaining* entry and a log. Fixing a typo is just another
  update — both entries stay in the history
- **Scan mode**: white background, full-width image, rotation. A barcode decoded from the
  screenshot is redrawn as SVG, so it stays sharp at any zoom
- **Adding**: send the bot a photo captioned "Rewe 50", or fill the form in the app
- **Expiry** guessed from the shop's rule when the card prints none — three years, or the
  end of the third calendar year (§199 BGB). A guess is marked "≈" so it never reads as a
  printed date, and the chat gets a reminder three days before
- **Comments** shared with the family, **history** of every change, **statistics** with a
  six-month chart
- **Access**: invite a member or another of your devices from inside the app, see every
  signed-in browser, sign a lost one out
- **Into the family chat**: new card, payment with the remainder, new comment, an expiry
  reminder, a weekly digest and a nightly backup file
- **Three languages** — English, German, Russian — picked automatically, no switch to set

## Screenshots

The demo dataset, so every figure here is made up.

| | | |
|---|---|---|
| [<img src="docs/screenshots/01-list.png" width="200">](docs/screenshots/01-list.png) | [<img src="docs/screenshots/02-scan.png" width="200">](docs/screenshots/02-scan.png) | [<img src="docs/screenshots/03-card.png" width="200">](docs/screenshots/03-card.png) |
| The list: soonest expiry first, what is left in large type | Scan mode: the barcode redrawn from the screenshot | A card: balance, history, comments |
| [<img src="docs/screenshots/04-stats.png" width="200">](docs/screenshots/04-stats.png) | [<img src="docs/screenshots/05-form.png" width="200">](docs/screenshots/05-form.png) | [<img src="docs/screenshots/06-access.png" width="200">](docs/screenshots/06-access.png) |
| Statistics: what you hold, where it goes, who spends | Adding a card by hand — two fields is the usual case | Access: invitations and signed-in devices |
| [<img src="docs/screenshots/07-dark.png" width="200">](docs/screenshots/07-dark.png) | | |
| Dark mode, following the phone or Telegram | | |

## Stack

| Layer | What |
|---|---|
| API | FastAPI, SQLAlchemy 2 (async), SQLite, Alembic |
| Bot | aiogram 3, long polling, same process |
| Frontend | React + TypeScript + Vite, served as static files by FastAPI |
| Auth | Telegram `initData` (HMAC) or a one-time link; a session cookie for the PWA |
| Deploy | Docker, one container, a `./data` volume |

## Local development

```bash
make install          # venv + npm install
make dev-api          # FastAPI :8000, DEV_MODE=true, bot off
make dev-web          # Vite :5173, proxies /api to :8000
make test             # pytest + vitest
make lint             # ruff + tsc
make migration m="…"  # alembic revision --autogenerate
```

Outside Telegram there is no `initData`, so in development the frontend sends
`X-Dev-User: 1000` and the backend accepts it only while `DEV_MODE=true`.
**In production `DEV_MODE` must be `false`** — otherwise the app is open to anyone.

End-to-end tests run against the built bundle served by FastAPI:

```bash
cd frontend && npm run build && npx playwright test
```

## Documentation

- [docs/deploy.md](docs/deploy.md) — putting it on a server: bot setup, reverse proxy,
  backups and a rehearsed restore, members without Telegram, and the traps a real VPS
  turned up
- [docs/internals.md](docs/internals.md) — how the demo, the languages and the access
  model work, and what to know before changing them

## Not built, on purpose

No OCR or vision recognition: after buying a card the two actions are "screenshot" and
"type the shop and the amount", and a recogniser has to beat that. No groups, households or
invites, no manual language switch. The model is recognition-ready (every field is
optional), but nothing fills it in automatically.

Maybe later: recognising the fields after all, a push aimed at one person rather than the
whole chat, Postgres if the data ever grows (`DATABASE_URL` is already external).

## Licence

MIT — see [LICENSE](LICENSE). The merchant tiles are drawn from initials and colours on
purpose: no third-party logos are shipped, so nothing here carries someone else's
trademark.

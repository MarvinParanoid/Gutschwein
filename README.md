# 🐷 Sparschwein

A family gift-card (Gutschein) manager: what is left on each card, who spent what, and a
screen the cashier can scan. Runs as a Telegram Mini App and as an installable PWA.

<img src="docs/demo.gif" alt="Finding a card, showing it at the till, writing down what is left" width="300">

**[Try the demo](https://spar-schwein.duckdns.org/demo)** — made-up cards, no account, nothing saved.

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
- **Comments** shared with the family, **history** of every change, **statistics** with a
  six-month chart
- **Into the family chat**: new card, payment with the remainder, new comment, an expiry
  reminder, a weekly digest and a nightly backup file
- **Two languages**, Russian and English, picked automatically with no switch to set

## Stack

| Layer | What |
|---|---|
| API | FastAPI, SQLAlchemy 2 (async), SQLite, Alembic |
| Bot | aiogram 3, long polling, same process |
| Frontend | React + TypeScript + Vite, served as static files by FastAPI |
| Auth | Telegram `initData` (HMAC) + a whitelist of Telegram ids; a session cookie for the PWA |
| Deploy | Docker, one container, a `./data` volume |

## Local development

```bash
make install          # venv + npm install
make dev-api          # FastAPI :8000, DEV_MODE=true, bot off
make dev-web          # Vite :5173, proxies /api to :8000
make test             # pytest
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

## Deploying to a VPS

You need a domain (A record to the server), Docker with the compose plugin, and ports
80/443 open. Telegram only opens a Mini App over **https with a valid certificate** — a
self-signed one or a bare IP will not do.

### 1. Bot and Mini App in @BotFather

```
/newbot                → name, username, gives you BOT_TOKEN
/setmenubutton         → pick the bot, enter https://sparschwein.example.com,
                         label the button
```

A separate Mini App (`/newapp`) is unnecessary: the menu button opens the same page.

### 2. Code and configuration

```bash
git clone <repo> /root/sparschwein && cd /root/sparschwein
cp .env.example .env && nano .env
```

Fill in `BOT_TOKEN`, `WEBAPP_URL`, `ALLOWED_TELEGRAM_IDS`, `FAMILY_CHAT_ID`,
`DEV_MODE=false`. Both ids come from one command: send the bot `/id` in a private chat
(your Telegram id) and in the family group after adding it there (the chat id, a negative
number). It answers people who are not on the whitelist yet, so nobody needs server access
to find their own id.

### 3. Permissions on the data volume

The container runs as uid 10001 while docker creates `./data` as root. Without this step
the app cannot write to the database:

```bash
mkdir -p data && sudo chown -R 10001:10001 data
```

### 4. Start

```bash
docker compose up -d --build
docker compose logs -f            # "running database migrations", then "telegram bot started"
curl -s localhost:8000/healthz    # {"status":"ok"}
```

Migrations apply themselves on startup. The container listens on `127.0.0.1:8000` only; the
reverse proxy is what faces the world.

### 5. Reverse proxy and TLS

Caddy gets and renews the certificate on its own, which makes it the shortest path.
`/etc/caddy/Caddyfile`:

```
sparschwein.example.com {
    reverse_proxy 127.0.0.1:8000
    # Caddy does not cap the body by default; set it just above the app's own
    # limit (12 MB per image) so junk is rejected earlier.
    request_body {
        max_size 15MB
    }
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        -Server
    }
}
```

For nginx you will also need certbot, `client_max_body_size 15m;` and
`proxy_set_header X-Forwarded-Proto $scheme;`.

### 6. Check

Open the bot → menu button → the app, and send it a photo: a draft should appear. If the
app says you have no access, the message carries your Telegram id — add it to
`ALLOWED_TELEGRAM_IDS` and run `docker compose up -d`.

### Field notes, all of them learned the hard way

- **Snap Docker cannot see `/opt`.** Installed as a snap (Ubuntu often does), the CLI and
  the daemon live in a confinement where paths outside `$HOME` do not exist: `docker
  compose` answers `no configuration file provided` and points at `/var/lib/snapd/void/`.
  Keep the project in `/root/sparschwein` instead; a bind mount from there works.
- **`localhost` may not resolve.** Some VPS images ship an `/etc/hosts` with only the
  machine's own hostname. Caddy dies on it (`lookup localhost on 8.8.8.8:53: no such
  host`), and it is not the only one. Add `127.0.0.1 localhost` and
  `::1 localhost ip6-localhost ip6-loopback`.
- **1 GB of RAM with no swap** will OOM during the frontend build. Two gigabytes of swap
  fix it: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon
  /swapfile`, plus the line in `/etc/fstab`.
- **Do not configure a log file in the Caddyfile**: the unit forbids writing to
  `/var/log/caddy` (`ProtectSystem`), and `journalctl -u caddy` has everything anyway.
- **Watch the disk.** Rebuilds leave dangling images behind; both deploy paths end with
  `docker image prune -f && docker builder prune -f`, and compose caps the json log files.

### Updating

```bash
make deploy-vps    # rsync + rebuild + wait for /healthz
```

The sync path is pinned to the Makefile's own directory, so it can be run from anywhere.
`data/` is excluded, and rsync never deletes excluded paths.

Pushing to `main` deploys through GitHub Actions instead, which is the safer route: CI
would have caught the missing dependency that once put production into a crash loop, and
`make deploy-vps` skips it.

### Backups

Every night (`BACKUP_HOUR_UTC`, 04:00 UTC by default) the bot sends an archive into the
family chat: the database plus every image. You read that chat daily anyway, so it is free
off-site storage with no keys and no second server. Out of schedule: `/backup`.

The database is captured through **sqlite's online backup API** rather than by copying the
file, because a copy taken mid-write can be unreadable; a test checks the snapshot with
`PRAGMA integrity_check`. If the archive does not fit Telegram's 45 MB limit, the images
are dropped and the caption says so.

### Restoring (rehearsed 2026-07-26)

```bash
cd /root/sparschwein
docker compose down
rm -rf data && mkdir data
tar xzf ~/sparschwein-2026-07-26.tar.gz -C data
# Required: the container runs as uid 10001 and SQLite needs to write.
chown -R 10001:10001 data
docker compose up -d
```

**That `chown` is not belt-and-braces.** Without it the app starts and `/healthz` honestly
answers `200`, because the health check never touches the database. Only the first write
fails, with `attempt to write a readonly database` — so the restore looks successful right
up until somebody tries to use it. The whole procedure was rehearsed in a second container
next to the live one, comparing cards, amounts, codes, images, comments and history.

## Demo

`https://<domain>/demo` is the same app on made-up cards. The link is safe to hand to
anyone: no account, and everything works — spend, comment, add, delete. The lock screen
that greets any uninvited visitor offers the same button.

The isolation is structural rather than a matter of permissions: in demo mode the HTTP
client is swapped for `src/demo/api.ts`, which answers from an object in the tab and
**makes no requests at all** — there is nothing to authorise. `e2e/demo.spec.ts` watches
every request the page makes and fails if one reaches `/api`.

That client reimplements the server's rules — spending writes an event, an empty card
closes itself, statistics are summed from the log — so a visitor tries the real behaviour,
not a set of screens. The data lives in the tab and is gone when it closes; card pictures
are drawn in the browser to keep other people's logos out of the repository.
`make demo-gif` re-records the animation above from the same dataset.

## Languages

Russian and English, with no switch by design: the language comes from wherever the app is
open — `initDataUnsafe.user.language_code` in Telegram, `navigator.language` in the PWA.
Anything that is neither `ru` nor `en` falls back to `DEFAULT_LANGUAGE`.

- `src/i18n/ru.ts` is the source of truth; `en.ts` is typed as `Dictionary = typeof ru`, so
  a forgotten key is a compile error rather than a blank.
- API errors are raised as a **key** (`Message("error.…")`) and rendered once at the
  boundary by the handlers in `main.py`. No helper has to carry a language through.
- The bot answers in the language of whoever wrote to it, and stores it on the user so
  background jobs know it without an incoming message. The family chat has no single
  reader, so its messages use `DEFAULT_LANGUAGE`.

## Access model

One shared family: any Telegram id in `ALLOWED_TELEGRAM_IDS` can see and edit every card.
There are no groups or roles — a deliberate omission.

Images are served from capability URLs — `/api/images/<yyyy-mm>/<32 hex>.webp` with no
authorisation, because `<img src>` cannot send headers. The filename is 128 bits of
randomness, unguessable and never listed, and a link can simply be forwarded into the
chat. If that ever stops being acceptable, serve them through `fetch` and a blob URL.

The PWA has no `initData`, so it uses a one-time link from `/login` in the bot, exchanged
for an httpOnly session cookie. Tokens are stored as SHA-256 hashes and die on first use.

## Not built, on purpose

No OCR or vision recognition: after buying a card the two actions are "screenshot" and
"type the shop and the amount", and a recogniser has to beat that. No groups, households or
invites, no manual language switch. The model is recognition-ready (every field is
optional), but nothing fills it in automatically.

Maybe later: recognising the fields after all, a push aimed at one person rather than the
whole chat, Postgres if the data ever grows (`DATABASE_URL` is already external).

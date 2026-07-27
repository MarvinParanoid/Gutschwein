# Running Gutschwein on a server

You need a domain (A record to the server), Docker with the compose plugin, and ports
80/443 open. Telegram only opens a Mini App over **https with a valid certificate** — a
self-signed one or a bare IP will not do.

To try the app before any of this, see [Run it yourself](../README.md#run-it-yourself):
three commands, no domain, no bot.

## 1. Bot and Mini App in @BotFather

```
/newbot                → name, username, gives you BOT_TOKEN
/setmenubutton         → pick the bot, enter https://gutschwein.example.com,
                         label the button
```

A separate Mini App (`/newapp`) is unnecessary: the menu button opens the same page.

Running without Telegram at all is possible — see [Members without Telegram](#members-without-telegram).

## 2. Code and configuration

```bash
git clone https://github.com/MarvinParanoid/Gutschwein /root/gutschwein
cd /root/gutschwein
cp .env.example .env && nano .env
```

Fill in `BOT_TOKEN`, `WEBAPP_URL`, `ALLOWED_TELEGRAM_IDS`, `FAMILY_CHAT_ID`,
`DEV_MODE=false`. Both ids come from one command: send the bot `/id` in a private chat
(your Telegram id) and in the family group after adding it there (the chat id, a negative
number). It answers people who are not on the whitelist yet, so nobody needs server access
to find their own id.

## 3. Permissions on the data volume

The container runs as uid 10001 while docker creates `./data` as root. Without this step
the app cannot write to the database:

```bash
mkdir -p data && sudo chown -R 10001:10001 data
```

## 4. Start

```bash
docker compose up -d --build
docker compose logs -f            # "running database migrations", then "telegram bot started"
curl -s localhost:8000/healthz    # {"status":"ok"}
```

Migrations apply themselves on startup. The container listens on `127.0.0.1:8000` only; the
reverse proxy is what faces the world.

## 5. Reverse proxy and TLS

Caddy gets and renews the certificate on its own, which makes it the shortest path.
`/etc/caddy/Caddyfile`:

```
gutschwein.example.com {
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

    # Access log into the journal. Caddy logs nothing by default, so without this
    # line there is no record of who ever opened the app.
    log
}
```

For nginx you will also need certbot, `client_max_body_size 15m;` and
`proxy_set_header X-Forwarded-Proto $scheme;`.

## 6. Check

Open the bot → menu button → the app, and send it a photo: a draft should appear. If the
app says you have no access, the message carries your Telegram id — add it to
`ALLOWED_TELEGRAM_IDS` and run `docker compose up -d`.

## Field notes, all of them learned the hard way

- **Snap Docker cannot see `/opt`.** Installed as a snap (Ubuntu often does), the CLI and
  the daemon live in a confinement where paths outside `$HOME` do not exist: `docker
  compose` answers `no configuration file provided` and points at `/var/lib/snapd/void/`.
  Keep the project in `/root/gutschwein` instead; a bind mount from there works.
- **`localhost` may not resolve.** Some VPS images ship an `/etc/hosts` with only the
  machine's own hostname. Caddy dies on it (`lookup localhost on 8.8.8.8:53: no such
  host`), and it is not the only one. Add `127.0.0.1 localhost` and
  `::1 localhost ip6-localhost ip6-loopback`.
- **1 GB of RAM with no swap** will OOM during the frontend build. Two gigabytes of swap
  fix it: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon
  /swapfile`, plus the line in `/etc/fstab`.
- **Do not point the Caddy log at a file**: the unit forbids writing under `/var/log/caddy`
  (`ProtectSystem`). A bare `log` goes to the journal, which is what you want anyway.
- **Watch the disk.** Rebuilds leave dangling images behind; both deploy paths end with
  `docker image prune -f && docker builder prune -f`, and compose caps the json log files.

## Updating

```bash
make deploy-vps    # rsync + rebuild + wait for /healthz
```

The sync path is pinned to the Makefile's own directory, so it can be run from anywhere.
`data/` is excluded, and rsync never deletes excluded paths. Machine-specific values live
in `.make.local` (gitignored) — copy the three defaults out of the Makefile.

Pushing to `main` deploys through GitHub Actions instead, which is the safer route: CI
would have caught the missing dependency that once put production into a crash loop, and
`make deploy-vps` skips it.

## Members without Telegram

Telegram is where the conveniences live — the photo-with-a-caption shortcut, the chat
notifications, the digest, the nightly backup — but it is not required. Leave `BOT_TOKEN`
and `FAMILY_CHAT_ID` empty and hand out sessions from the console:

```bash
docker compose exec app python -m app.invite "Anna"   # prints a one-time login link
docker compose exec app python -m app.invite --link 3 # another link for member 3
docker compose exec app python -m app.invite --list
docker compose exec app python -m app.invite --revoke 3
```

The console is only needed for the **first** member. After that the app itself does it:
*Access* in the burger menu mints the same link for a new member or for another of your own
devices, and lists every signed-in browser with a way to sign one out — the answer to a
lost phone. Every invitation is announced in the family chat, because minting a way in is
the one event nobody should miss.

The link is the same credential the bot hands out: 256 bits of randomness, stored only as
a SHA-256 digest, valid ten minutes, single use, carried in the URL fragment so it never
reaches a server log. Opening it sets the same session cookie. Only the trust anchor moves
— from "Telegram vouches that this chat is Anna" to "whoever has a shell here does".

Both doors work at once, so one member can refuse Telegram while the rest keep using the
Mini App. Membership is checked on every request either way: a Telegram member is in
exactly while their id is in `ALLOWED_TELEGRAM_IDS`, a console member exactly while their
row exists — which is why `--revoke` deletes their sessions before the row.

A Telegram-less install has **no automatic backup**, because the nightly archive goes into
the family chat. Back up `./data` yourself.

## Backups

Every night (`BACKUP_HOUR_UTC`, 04:00 UTC by default) the bot sends an archive into the
family chat: the database plus every image. You read that chat daily anyway, so it is free
off-site storage with no keys and no second server. Out of schedule: `/backup`.

The database is captured through **sqlite's online backup API** rather than by copying the
file, because a copy taken mid-write can be unreadable; a test checks the snapshot with
`PRAGMA integrity_check`. If the archive does not fit Telegram's 45 MB limit, the images
are dropped and the caption says so.

The archive carries the card codes, both in the database and in the pictures — so they end
up on Telegram's servers a second time. Leaving `FAMILY_CHAT_ID` empty switches the whole
mechanism off.

## Restoring (rehearsed 2026-07-26)

```bash
cd /root/gutschwein
docker compose down
rm -rf data && mkdir data
tar xzf ~/gutschwein-2026-07-26.tar.gz -C data
# Required: the container runs as uid 10001 and SQLite needs to write.
chown -R 10001:10001 data
docker compose up -d
```

**That `chown` is not belt-and-braces.** Without it the app starts and `/healthz` honestly
answers `200`, because the health check never touches the database. Only the first write
fails, with `attempt to write a readonly database` — so the restore looks successful right
up until somebody tries to use it. The whole procedure was rehearsed in a second container
next to the live one, comparing cards, amounts, codes, images, comments and history.

## Who opened it

With the `log` line in the Caddyfile, [`deploy/demo-stats`](../deploy/demo-stats) counts
visitors out of the journal. Copy it to the server once:

```bash
scp deploy/demo-stats root@your-server:/usr/local/bin/ && ssh root@your-server chmod +x /usr/local/bin/demo-stats
```

Then `make stats` (or `make stats SINCE="3 days ago"`) reads it over ssh. It separates a
signed-in member from a demo visitor by a property of the app rather than a guess: the demo
client never calls the API, a signed-in member calls `/api/me` on every load. Numbers are
undercounts — the service worker serves repeat visits from cache without reaching the
server at all.

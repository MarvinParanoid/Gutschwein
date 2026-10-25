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
docker compose pull && docker compose up -d
docker compose logs -f            # "running database migrations", then "telegram bot started"
curl -s localhost:8000/healthz    # {"status":"ok"}
```

The image comes from `ghcr.io/marvinparanoid/gutschwein:latest`, published by CI only
after it has built the image, started it and watched it answer — see the `docker` job.
Nothing is compiled on your server, which matters on a small one: the frontend build is
what once ran a 1 GB VPS out of memory.

`docker compose up -d --build` still builds from the checkout instead, which is what a
developer wants and the only way to run changes that are not pushed yet.

A git tag `v*` publishes an image under that name and deliberately leaves `:latest` alone,
which belongs to `main`. Every commit on `main` is also tagged with its first twelve
characters, and a deploy is always pinned to one of those tags rather than to whatever
`:latest` points at by the time the server gets round to pulling.

## Releasing and rolling back

A push **never deploys**. It runs the checks and, on `main`, publishes the image; putting
it into production is a separate, deliberate step, because a release can carry a
migration and the moment for that is chosen, not inherited from a `git push`.

To release: GitHub → Actions → **Deploy** → Run workflow, on `main`, with the commit's sha.
The workflow refuses unless the commit is on `main`, its CI run on `main` succeeded
(backend, frontend, image smoke test *and* e2e — the image itself is published before e2e
finishes, so its presence alone proves less), and `gutschwein:<first 12 of the sha>` is in
the registry. Then it asks the server for exactly that tag, through the deploy key, whose
forced command (`/root/deploy.sh`) can do nothing else. Two runs of the workflow never
overlap: a second waits for the first, and a third replaces the waiting second. The
break-glass path below is not part of that queue — do not use it while a run is going.

To roll back: the same workflow with the earlier commit. Images `main` produced stay in the
registry (nothing deletes them unless the package settings are told to), so an old one
needs no rebuild. **If a migration lies between the
two commits, take the schema back first**, with the newer image and the app stopped — an
older image refuses to start on a database newer than itself:

```bash
cd /root/sparschwein                                   # the deployment directory
docker compose stop app
docker compose run --rm app alembic downgrade <revision the older commit expects>
```

then run **Deploy** with the older commit.

What a rollback swaps is the **image only**. `deploy.sh` always resets the server's
checkout to the current `main` first, whatever tag it was given, so `docker-compose.yml`
and every other file there come from today's `main` while the container runs the older
image. That is harmless while `docker-compose.yml` and `.env` mean the same thing to both
versions — check that before rolling back across a change to either.

From the server itself, without GitHub (the break-glass path — it skips the CI check):

```bash
ssh root@your-server "deploy <12-char sha>"    # what the workflow sends
ssh root@your-server dry-run                   # what is running, with its digest
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
  Pulled images are *tagged*, so prune ignores them — the deploy script keeps the running
  one, `:previous`, and the two newest other release tags, and deletes the rest.
- **Snap Docker also strips the environment.** `GUTSCHWEIN_TAG=… docker compose config`
  comes out with `:latest` regardless: the variable never crosses the confinement, so
  compose interpolation cannot be driven from the shell. The deploy script therefore pulls
  `:<sha>` and renames it to `:latest` locally, deciding on this machine what `:latest`
  means. On an unconfined Docker the variable works as written in `docker-compose.yml`.

## Updating

Production is updated by the **Deploy** workflow (see *Releasing and rolling back*),
which runs `/root/deploy.sh` on the server. Its source is
[`deploy/deploy.sh`](../deploy/deploy.sh); after changing it, install it by hand — the
deploy key can only run it, not replace it:

```bash
scp deploy/deploy.sh root@your-server:/root/deploy.sh
# Check it with dry-run: without a command the script means "deploy :latest".
ssh root@your-server 'chmod 700 /root/deploy.sh && SSH_ORIGINAL_COMMAND=dry-run /root/deploy.sh'
```

What one deployment does, in order:

1. **Takes a host-wide lock** (`/run/lock/gutschwein-deploy.lock`). A second deployment —
   from the workflow or by hand — stops at once without touching anything.
2. **Preflight, with the app still running:** `.env` present, enough free disk for a
   snapshot (data size + 1 GB) and for the image, the image pulled, and an **import check**:
   `python -c "import app.main"` in the new image, without network. That proves the image
   is intact and its code and dependencies import — not that the app starts: configuration,
   the database, the migrations and the bot are first exercised by the real start in step 5.
   Any failure here leaves the running version as it was.
3. **Keeps the running image as `:previous`** — by the ID of the container that is running,
   and only if that container is *healthy*. After a failed deployment the running container
   is the failed one, so `:previous` keeps pointing at the last version that was healthy.
   Image cleanup skips `:previous` by name, so a rollback candidate is always on the
   machine, without the registry.
4. **Stops the app and snapshots it** into `/root/gutschwein-snapshots/<UTC time>-<tag>/` —
   outside the git checkout, so no git command there can touch it: the database through
   SQLite's backup API (consistent, committed WAL included, checked with
   `PRAGMA integrity_check`, stored as one self-contained file), a full independent copy of
   `uploads/` compared file by file, and `snapshot.txt` (images, whether the old container
   was healthy, schema revision, row counts, checksum). A snapshot is complete only once
   its directory loses the `.partial` suffix. The newest five are kept.
5. **Starts the new version**, whose startup runs the migrations, and waits for
   `/healthz`.

Nothing is rolled back, restored or downgraded automatically. If the new version does not
come up, the script says which snapshot and which image to go back to, and leaves the
decision to you.

**Never run `git clean -x` in `/root/sparschwein`.** `.env` and `data/` live in that
checkout untracked, and `-x` deletes them. `deploy.sh` only fetches and resets, which leaves
untracked files alone.

### Interrupted deployments

Interrupted by Ctrl-C, `SIGTERM`, or the ssh session dropping (a cancelled workflow run)
**before step 5**, the script cleans up after itself: an incomplete snapshot is deleted and
the old container is started again. That container's database was only read, so this
resumes it rather than rolling anything back. Interrupted during or after step 5, nothing is
undone: the new version may already have migrated the database.

Killed outright (`kill -9`, out of memory) or cut off by a reboot, the script cannot clean
up. It leaves `/root/gutschwein-snapshots/in-progress`, which names the stage it reached,
and `dry-run` shows it:

```bash
ssh root@your-server 'SSH_ORIGINAL_COMMAND=dry-run /root/deploy.sh'
```

| `stage=` | State it left | What to do |
|---|---|---|
| `preflight` | old app untouched (maybe a new image pulled, `:previous` re-tagged) | nothing; deploy again |
| `stopping-old`, `snapshot` | old app **stopped** (a reboot does not restart it: compose stopped it on purpose); maybe a `*.partial` snapshot | `cd /root/sparschwein && docker compose start app`; the next deployment removes the `.partial` |
| `switching` | old container being replaced; the app may be down; **the database may be partly migrated** | see below — deployments are blocked until you clear the note |
| `health` | the new version is running, maybe still migrating | see below — deployments are blocked until you clear the note |

The note is also left, on purpose, when a deployment *fails* at `switching` or `health`:
the new version may have started and migrated. It is removed after every other outcome.

**A note from `switching` or `health` — or one whose stage cannot be read — blocks every
further deployment**, and nothing removes it, because it is the only record that the
database may be half-migrated. Find out what state it is in: `docker compose logs app`,
the revision in `alembic_version` against the one the new image expects. Then either fix
forward or go back to the snapshot (below), and only then move the note aside — never
delete it:

```bash
mv /root/gutschwein-snapshots/in-progress /root/gutschwein-snapshots/in-progress.reviewed-$(date -u +%Y%m%dT%H%M%SZ)
```

A note from an earlier stage (`preflight`, `stopping-old`, `snapshot`) does not block: the
database was at most read. The next deployment prints it and carries on. The database is
never changed by the script itself — only by the new version's startup, from `switching`
on.

`dry-run` is read-only: it pulls, tags, starts, stops, creates and deletes nothing, takes no
lock, and works while a deployment is running.

Going back to the snapshot by hand — this **discards everything written since it was
taken**, so it is for a deployment that failed, not for one that has been in use:

```bash
cd /root/sparschwein
docker compose stop app
mv data data.before-restore-$(date -u +%Y%m%dT%H%M%SZ)          # never delete it
mkdir -p data
cp -a /root/gutschwein-snapshots/<name>/gutschwein.db /root/gutschwein-snapshots/<name>/uploads data/
chown -R 10001:10001 data
docker tag ghcr.io/marvinparanoid/gutschwein:previous ghcr.io/marvinparanoid/gutschwein:latest
GUTSCHWEIN_TAG=latest docker compose up -d
```

The snapshot directory holds every card's code, so it is `700` and belongs on the server
only.

## Re-reading the barcodes

A voucher's barcode is decoded once, when its picture is uploaded, so a card the decoder
could not read then stays unreadable after the decoder improves. `app.rescan` reads the
stored pictures again:

```bash
docker compose exec app python -m app.rescan           # what would change, writes nothing
docker compose exec app python -m app.rescan --apply   # write it
docker compose exec app python -m app.rescan --all --apply
```

Without `--all` it only looks at vouchers that have no barcode yet. It never overwrites a
code someone typed, and a picture that still refuses keeps whatever it had — a rescan may
only add. Run it after an update that touches `app/barcode.py`.

## Members without Telegram

Telegram is where the conveniences live — the photo-with-a-caption shortcut, the chat
notifications, the digest, the nightly backup — but it is not required. Leave `BOT_TOKEN`
and `FAMILY_CHAT_ID` empty and hand out sessions from the console:

```bash
docker compose exec app python -m app.invite "Anna"       # a console root, prints a one-time link
docker compose exec app python -m app.invite --link 3     # another link for member 3
docker compose exec app python -m app.invite --list       # everyone, and whether they get in
docker compose exec app python -m app.invite --revoke 3   # end a membership (and their invitees')
docker compose exec app python -m app.invite --restore 3  # undo that
docker compose exec app python -m app.invite --sessions-off 3  # sign out devices, keep membership
docker compose exec app python -m app.invite --prune      # sign out everyone refused now
```

`--revoke` ends a membership: it marks the member revoked, and ends the sessions and unused
links of everyone invited through them in the same transaction. The row itself is deleted
only for a member who left no history (vouchers, comments, events) and invited nobody;
otherwise it stays, revoked, because history points at it — deleting it used to let SQLite
hand the freed id to the next member, who then inherited the history. `--restore` lifts the
revocation and with it the refusal of their invitees, but the sessions it ended stay ended:
everyone needs a new link (`--link`).

`--sessions-off` is a different thing: it signs a member out of every device and drops
their unused links, and leaves their membership — and their invitees — as they were.

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
exactly while their id is in `ALLOWED_TELEGRAM_IDS`; a member invited in the app is in
exactly while whoever invited them is — so taking someone off the list locks out the people
they invited too, on the next request. Putting them back lets those people in again with
the sessions they still have. `--prune` after the change signs those devices out, so they
come back only through a new link — but it ends no membership: to lock someone out for
good, `--revoke` them.

### Revision 0011: one card per picture

0011 adds a unique index on the picture column. If two cards still share one picture
from before the app refused that, the upgrade stops, the app does not start, and the log
names the picture and the cards, with the one command that detaches it from all but one
of them. Nothing is changed until you run it; then start again and upload the detached
cards' screenshots in the app. To check beforehand, read-only:

```sql
SELECT image_path, group_concat(id) FROM vouchers
WHERE image_path IS NOT NULL GROUP BY image_path HAVING count(*) > 1;
```

### Upgrading to provenance (revision 0010)

Before 0010 an invitation from the app left no record of who sent it, and that is how a
member taken off the list kept access through their invitees. The migration therefore
decides only what the data proves:

- **No Telegram member has ever existed** in the database (and no history points at a
  deleted member): every member without Telegram was created from the console, and all
  of them become console roots. A Telegram-free install keeps working with no action.
- **Otherwise** members without Telegram are left **unconfirmed** and are refused until you
  decide. The migration log and every start of the app list them by id and name.

Afterwards, for each `unconfirmed` member in `--list`:

```bash
docker compose exec app python -m app.invite --list
docker compose exec app python -m app.invite --confirm 4        # you vouch for them
docker compose exec app python -m app.invite --set-inviter 4 1  # invited by member 1
docker compose exec app python -m app.invite --revoke 4         # nobody knows them
```

`--set-inviter` is the more accurate answer when you know who invited them: their access
then follows that member's. The family chat's "… invited …" messages are the only record
of who that was. Their existing sessions start working again as soon as they are
confirmed — unless `--prune` was run in between, which deletes them. A link they tried
while refused is used up; give them a new one with `--link`.

Recovery: an allowlist typo is fixed by correcting `.env` and restarting — nothing was
written. A revocation by mistake is `--restore` plus a new `--link`. With no root left at
all, `python -m app.invite "Name"` always creates a new one. Going back to an image older
than 0010 needs the schema taken back first, by the newer image — the app migrates forward
on every start, so run it as a one-off and then switch images:
`docker compose run --rm app alembic downgrade 0009`. It removes the three columns and
nothing else.

A Telegram-less install has **no automatic backup**, because the nightly archive goes into
the family chat. Back up `./data` yourself — the whole directory, not just the `.db`: SQLite
runs in WAL mode, so recent transactions live in the `-wal` file next to it until they are
checkpointed. The nightly archive is unaffected, it snapshots through sqlite's backup API
and writes one complete file.

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

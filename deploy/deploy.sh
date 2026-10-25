#!/bin/sh
# Deploy target for the GitHub Actions key. Forced via authorized_keys, so this is
# the only thing that key can do — no shell, no file access, no port forwarding.
# Installed on the server as /root/deploy.sh; this file is its source.
#
#   deploy <12-char sha>   pull that image and switch to it
#   deploy                 the same with :latest
#   dry-run                report state, change nothing
#
# Before anything is stopped, the disk is checked and the new image is pulled and
# import-checked; a failure there leaves the running version untouched. Then the
# app is stopped, the database and the pictures are snapshotted, and only then is
# the new version started — whose startup runs the migrations. Nothing here ever
# restores a snapshot or downgrades a schema on its own: when the new version does
# not come up, it says so and leaves the decision to a person.
#
# Interrupted (Ctrl-C, SIGTERM, the ssh session dropping) before the new version
# is started, the run removes its incomplete snapshot and starts the old container
# again. Killed outright or by a reboot, it leaves $SNAPSHOTS/in-progress naming
# the stage it reached; dry-run shows it, and docs/deploy.md says what to do.
set -eu

REPO=https://github.com/MarvinParanoid/Gutschwein.git
IMAGE=ghcr.io/marvinparanoid/gutschwein
# Production values. Only a shell on the server (or the tests) can override them:
# sshd hands the forced command no environment of the client's choosing.
DIR=${DEPLOY_DIR:-/root/sparschwein}
LOCK=${DEPLOY_LOCK:-/run/lock/gutschwein-deploy.lock}
MIN_FREE_MB=${DEPLOY_MIN_FREE_MB:-1024}
KEEP_SNAPSHOTS=${DEPLOY_KEEP_SNAPSHOTS:-5}
HEALTH_TRIES=${DEPLOY_HEALTH_TRIES:-30}
HEALTH_DELAY=${DEPLOY_HEALTH_DELAY:-2}
# Outside the checkout, so no git operation on it can ever touch a snapshot.
SNAPSHOTS=${DEPLOY_SNAPSHOTS:-/root/gutschwein-snapshots}
PROGRESS="$SNAPSHOTS/in-progress"
cd "$DIR"

# The real stdout, kept for the EXIT trap: a failure inside the snapshot block runs
# the trap with that block's redirection still in force.
exec 8>&1
# Never fails: it also speaks from the EXIT trap, after the client may be gone.
say() { printf '%s\n' "$*" >&8 2>/dev/null || true; }
die() { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }

# A complete snapshot's directory name; anything else under $SNAPSHOTS is not one.
SNAPSHOT_NAME='^[0-9]{8}T[0-9]{6}Z-([0-9a-f]{12}|latest)$'

# "deploy <sha>" pins the image; plain "deploy" takes :latest. The command
# arrives from the forced key, so this is the only place it can be chosen.
ACTION=$(printf %s "${SSH_ORIGINAL_COMMAND:-deploy}" | cut -d" " -f1)
TAG=$(printf %s "${SSH_ORIGINAL_COMMAND:-}" | cut -d" " -s -f2)
export GUTSCHWEIN_TAG="${TAG:-latest}"

if [ "$ACTION" = "dry-run" ]; then
    echo "dry-run: каталог $DIR"
    if [ -d .git ]; then
        echo "git: $(git rev-parse --short HEAD 2>/dev/null || echo нет коммитов)"
    else
        echo "git: не репозиторий — первый деплой сделает bootstrap"
    fi
    echo ".env на месте: $([ -f .env ] && echo да || echo НЕТ)"
    echo "данных в томе: $(find data -type f 2>/dev/null | wc -l) файлов"
    echo "образ: $(docker inspect --format "{{.Config.Image}}" sparschwein-app-1 2>/dev/null || echo нет)"
    echo "digest: $(docker inspect --format "{{index .RepoDigests 0}}" ghcr.io/marvinparanoid/gutschwein:latest 2>/dev/null | cut -d@ -f2 | cut -c1-19 || echo -)"
    echo "кандидат для отката (:previous): $(docker image inspect --format "{{.Id}}" "$IMAGE:previous" 2>/dev/null | cut -c8-19 || echo нет)"
    # shellcheck disable=SC2010  # snapshot names are generated below: timestamp-tag
    echo "последний снимок: $(ls -1 "$SNAPSHOTS" 2>/dev/null | grep -E "$SNAPSHOT_NAME" | sort | tail -n 1 || true)"
    if [ -f "$PROGRESS" ]; then
        echo "ПРЕРВАННЫЙ ДЕПЛОЙ (см. docs/deploy.md, «Interrupted deployments»):"
        sed 's/^/  /' "$PROGRESS"
    fi
    docker compose ps --format "{{.Service}} {{.Status}}"
    exit 0
fi

[ "$ACTION" = "deploy" ] || die "неизвестная команда: $ACTION"
# A tag goes into image references and a directory name: twelve hex characters
# exactly. `case` sees the whole value, newlines included, unlike a line-wise grep.
if [ "$GUTSCHWEIN_TAG" != "latest" ]; then
    case "$GUTSCHWEIN_TAG" in
        *[!0-9a-f]*) die "тег должен быть 12 шестнадцатеричных символов" ;;
    esac
    [ ${#GUTSCHWEIN_TAG} -eq 12 ] || die "тег должен быть 12 шестнадцатеричных символов"
fi

# One deployment at a time on this host, whoever starts it: the GitHub workflow and
# a manual `deploy` both come through here. Held until the script exits.
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || die "уже идёт другой деплой (замок $LOCK) — ничего не тронуто"

# A run that ended while the new version was being switched in or checked may have
# left the database half-migrated, and its note is the only record of that. Nothing
# goes ahead — and nothing removes the note — until a person has looked and moved it
# aside. Checked before the EXIT trap exists, so refusing cannot clean anything up.
# Only the stages before the switch, where the database was at most read, let a
# deployment continue; an unknown or damaged note counts as the worst case.
if [ -f "$PROGRESS" ]; then
    case "$(sed -n 's/^stage=//p' "$PROGRESS")" in
        preflight | stopping-old | snapshot) ;;
        *)
            sed 's/^/  /' "$PROGRESS" >&2
            die "предыдущий деплой оборвался после переключения — база могла остаться частично мигрированной. Ничего не тронуто. Разберитесь (docs/deploy.md, «Interrupted deployments») и уберите записку: mv $PROGRESS $PROGRESS.reviewed-\$(date -u +%Y%m%dT%H%M%SZ)"
            ;;
    esac
fi

# What to undo if this run stops half-way. Only two things are ever undone: an
# incomplete snapshot is removed, and the old container — stopped by this run for
# the snapshot, before the new version was started — is started again. Its
# database was only read, so that is resuming it, not rolling anything back.
PARTIAL=""
STOPPED_OLD=0
old_cid=""
old_id=""
snapshot=""
STAGE=""
# shellcheck disable=SC2329  # invoked through the EXIT trap
cleanup() {
    status=$?
    trap - EXIT
    set +e  # undo as much as possible, whatever fails along the way
    if [ -n "$PARTIAL" ] && [ -d "$PARTIAL" ]; then
        rm -rf "$PARTIAL"
        say "незавершённый снимок удалён: $PARTIAL"
    fi
    if [ "$STOPPED_OLD" = 1 ]; then
        say "возвращаю прежний контейнер: новая версия не запускалась, база не менялась"
        docker compose start app >/dev/null 2>&1 || say "ВНИМАНИЕ: прежний контейнер не запустился — docker compose start app"
    fi
    # The note stays where the outcome is unclear — the new version may have started
    # and migrated — and goes everywhere else: success, or nothing was switched.
    if [ "$status" -ne 0 ] && { [ "$STAGE" = switching ] || [ "$STAGE" = health ]; }; then
        say "состояние сохранено в $PROGRESS (stage=$STAGE) — его покажет dry-run"
    else
        rm -f "$PROGRESS"
    fi
    exit "$status"
}
trap cleanup EXIT
# dash runs the EXIT trap on its own exit only, not when a signal kills it — so
# every signal that can interrupt a deployment is turned into an exit. SIGHUP is
# what a dropped ssh session (a cancelled workflow run) sends; SIGPIPE, what the
# next line of output would raise once nobody reads it. Ignored, a write to the
# vanished client fails instead, and `set -e` turns that into an exit as well.
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap '' PIPE

# Where the run is, for whoever finds the host after it was killed (-9, reboot)
# without a chance to clean up. Removed on every exit the run gets to handle.
progress() {
    STAGE=$1
    printf '%s\n' "stage=$1" "since=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "tag=$GUTSCHWEIN_TAG" \
        "old_container=$old_cid" "old_image=$old_id" "snapshot=$snapshot" \
        > "$PROGRESS.tmp" && mv "$PROGRESS.tmp" "$PROGRESS"
}

mkdir -p "$SNAPSHOTS"
chmod 700 "$SNAPSHOTS"  # the database inside carries every card's code
if [ -f "$PROGRESS" ]; then  # only a stage before the switch gets this far
    say "ВНИМАНИЕ: предыдущий деплой был прерван до переключения, база не менялась:"
    sed 's/^/  /' "$PROGRESS" >&8 2>/dev/null || true
fi
progress preflight
# Left by a run that was killed outright; nothing else can be writing them now.
rm -rf "$SNAPSHOTS"/*.partial

# One-time bootstrap: the directory was populated by rsync before CI existed.
if [ ! -d .git ]; then
    echo "bootstrap: превращаю $DIR в git-checkout"
    git init -q -b main
    git remote add origin "$REPO"
fi

git fetch -q --depth 1 origin main
# Untracked files (.env, data/) are left alone by reset; snapshots are not in here.
git reset -q --hard FETCH_HEAD
echo "развёрнут коммит $(git rev-parse --short HEAD)"

# --- preflight: nothing below may fail once the app is stopped -------------------

[ -f .env ] || die ".env не найден в $DIR — ничего не тронуто"

free_mb() { df -Pk "$1" | awk 'NR == 2 { print int($4 / 1024) }'; }
data_mb() { du -sk data/gutschwein.db* data/uploads 2>/dev/null | awk '{ s += $1 } END { print int(s / 1024) + 1 }'; }

need=$(($(data_mb) + MIN_FREE_MB))
have=$(free_mb "$SNAPSHOTS")
[ "$have" -ge "$need" ] || die "мало места под снимок: свободно $have МБ, нужно $need — ничего не тронуто"
docker_root=$(docker info --format '{{.DockerRootDir}}')
have=$(free_mb "$docker_root")
[ "$have" -ge "$MIN_FREE_MB" ] || die "мало места для образа: свободно $have МБ, нужно $MIN_FREE_MB — ничего не тронуто"

# Pulled, not built: nothing is compiled on a 1 GB box, and what runs here is the
# image CI already built, started and tested. A tag missing from the registry fails
# loudly instead of quietly falling back to a local build.
echo "образ $GUTSCHWEIN_TAG"
docker pull -q "$IMAGE:$GUTSCHWEIN_TAG" >/dev/null \
    || die "не удалось скачать $IMAGE:$GUTSCHWEIN_TAG — работающая версия не тронута"
new_id=$(docker image inspect --format '{{.Id}}' "$IMAGE:$GUTSCHWEIN_TAG") \
    || die "образ $GUTSCHWEIN_TAG не найден после скачивания — работающая версия не тронута"
# An import check, not a start: it proves the layers are intact and the code and its
# dependencies import — not that the app starts. Configuration, the database, the
# migrations and the bot are first exercised by the real start below.
docker run --rm --network none --entrypoint python "$IMAGE:$GUTSCHWEIN_TAG" -c "import app.main" \
    >/dev/null 2>&1 || die "образ $GUTSCHWEIN_TAG не проходит проверку импорта — работающая версия не тронута"

# The rollback candidate is the image of the container running now — by its ID, not
# by whatever :latest names — and only if that container is healthy. After a failed
# deployment the running container is the failed one; tagging it would replace the
# last good image with it. A tag is what keeps the candidate: an image with a name
# is neither dangling for `image prune` nor removed by the retention below, which
# skips :previous by name.
old_cid=$(docker compose ps -q app 2>/dev/null || true)
old_state="- none"
if [ -n "$old_cid" ]; then
    old_state=$(docker inspect --format '{{.Image}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$old_cid")
    old_id=${old_state%% *}
    if [ "${old_state#* }" = "healthy" ]; then
        docker tag "$old_id" "$IMAGE:previous"
        echo "работающий образ сохранён как :previous"
    else
        echo "работающий контейнер не healthy (${old_state#* }) — :previous остаётся прежним"
    fi
fi

# --- snapshot: the app is stopped, so nothing is written after it ----------------

if [ -f data/gutschwein.db ]; then
    snapshot="$(date -u +%Y%m%dT%H%M%SZ)-$GUTSCHWEIN_TAG"
    PARTIAL="$SNAPSHOTS/$snapshot.partial"
    if [ -n "$old_cid" ]; then
        # Both before the stop: a signal during it must start the app again, and a
        # kill during it must leave a note saying the app may be down.
        STOPPED_OLD=1
        progress stopping-old
        docker compose stop app >/dev/null
    fi
    progress snapshot
    mkdir "$PARTIAL"
    {
        echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "from_image=$old_id"
        echo "from_state=${old_state#* }"
        echo "to_tag=$GUTSCHWEIN_TAG"
        echo "to_image=$new_id"
        # SQLite's backup API, not a file copy: it reads committed transactions
        # still sitting in the -wal file too, and never a half-written page.
        python3 - "$DIR/data/gutschwein.db" "$PARTIAL/gutschwein.db" <<'PY' || die "снимок базы не удался"
import hashlib, sqlite3, sys
from pathlib import Path
source = sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
source.backup(target)
source.close()
# The copy inherits WAL mode; one self-contained file is what a snapshot should be.
target.execute("PRAGMA journal_mode=DELETE")
result = target.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    sys.exit(f"integrity_check: {result}")
def value(query):
    try:
        return target.execute(query).fetchone()[0]
    except sqlite3.Error:
        return "-"
print(f"alembic_version={value('SELECT version_num FROM alembic_version')}")
for table in ("users", "vouchers", "events", "comments", "sessions"):
    print(f"rows_{table}={value(f'SELECT count(*) FROM {table}')}")
target.close()
print("db_sha256=" + hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest())
PY
        if [ -d data/uploads ]; then
            # Copies, not hard links: a snapshot must survive anything done to the
            # live files, including a write that reuses the inode.
            cp -a data/uploads "$PARTIAL/uploads" || die "копия картинок не удалась"
            python3 - "$DIR/data/uploads" "$PARTIAL/uploads" <<'PY' || die "копия картинок не совпадает с оригиналом"
import hashlib, sys
from pathlib import Path
def tree(root):
    root = Path(root)
    return {
        p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_ino)
        for p in root.rglob("*") if p.is_file()
    }
live, copy = tree(sys.argv[1]), tree(sys.argv[2])
if {k: v[0] for k, v in live.items()} != {k: v[0] for k, v in copy.items()}:
    sys.exit("file lists or contents differ")
if any(live[k][1] == copy[k][1] for k in live):
    sys.exit("a copy shares an inode with the original")
print(f"uploads_files={len(copy)}")
print(f"uploads_bytes={sum(p.stat().st_size for p in Path(sys.argv[2]).rglob('*') if p.is_file())}")
PY
        fi
    } > "$PARTIAL/snapshot.txt.tmp" || die "снимок не удался"
    mv "$PARTIAL/snapshot.txt.tmp" "$PARTIAL/snapshot.txt"
    # The rename is what marks a snapshot complete; *.partial never is.
    mv "$PARTIAL" "$SNAPSHOTS/$snapshot"
    PARTIAL=""
    echo "снимок: snapshots/$snapshot"
fi

# --- switch ------------------------------------------------------------------------

# Pulled by tag and renamed to :latest locally as well, so a plain `deploy` and
# compose's default both mean what was deployed last.
if [ "$GUTSCHWEIN_TAG" != "latest" ]; then
    docker tag "$IMAGE:$GUTSCHWEIN_TAG" "$IMAGE:latest"
fi
# From here the old container is being replaced: if this fails, starting "the old
# one" could start the new one instead, so nothing is done automatically.
progress switching
STOPPED_OLD=0
docker compose up -d \
    || die "новый контейнер не создан. Снимок: snapshots/${snapshot:-нет}; прежний образ: $IMAGE:previous"

# Each build leaves the previous image dangling; on a 15 GB disk that adds up to
# an outage. Tagged images (the VPN, pihole) are untouched by these two.
docker image prune -f >/dev/null
docker builder prune -f >/dev/null

# Release tags are kept for the running one, :previous, and the two newest others;
# older ones go. Sorted by creation time, which leads each line.
docker images --format '{{.CreatedAt}}|{{.Tag}}' "$IMAGE" |
    grep -v -e '|latest$' -e '|previous$' -e "|$GUTSCHWEIN_TAG\$" |
    sort -r | tail -n +3 | cut -d"|" -f2 |
    while read -r old; do
        [ -n "$old" ] && docker rmi "$IMAGE:$old" >/dev/null 2>&1 || true
    done
if [ -n "$old_id" ] && ! docker image inspect "$IMAGE:previous" >/dev/null 2>&1; then
    say "ВНИМАНИЕ: :previous пропал после очистки — откатываться будет не на что без сети"
fi

# shellcheck disable=SC2010  # snapshot names are generated above: timestamp-tag
ls -1 "$SNAPSHOTS" | grep -E "$SNAPSHOT_NAME" | sort -r | tail -n +"$((KEEP_SNAPSHOTS + 1))" |
    while read -r old; do
        [ -n "$old" ] && rm -rf "${SNAPSHOTS:?}/$old"
    done

progress health
i=0
while [ $i -lt "$HEALTH_TRIES" ]; do
    if curl -fsS http://127.0.0.1:8000/healthz; then
        echo " — поднялся"
        exit 0
    fi
    i=$((i + 1))
    sleep "$HEALTH_DELAY"
done
echo "healthcheck не прошёл. Ничего не откатывается автоматически."
echo "Снимок перед деплоем: snapshots/${snapshot:-нет}; прежний образ: $IMAGE:previous"
docker compose logs --tail=50 app
exit 1

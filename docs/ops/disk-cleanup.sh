#!/usr/bin/env bash
#
# Disk cleanup for the shared VPS — prepared after the November 2026 investigation
# (docs/ops/disk-usage-2026-11.md), NOT run by anyone yet.
#
#   ./disk-cleanup.sh            # report what would go, change nothing (the default)
#   ./disk-cleanup.sh --apply    # do it, after reading the report
#
# Most of what it touches belongs to other projects on the server (yapped), so it
# needs their owner's agreement first. It never touches:
#   - an image any container uses, running or stopped;
#   - Gutschwein's images (the running one and :previous are the rollback);
#   - volumes, the build cache, databases, backups or any data directory.
# No `docker system prune`: that would take whatever is unused at the moment,
# including a rollback image someone is about to need.

set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1
# How many of yapped's images to keep besides the ones containers use: the
# newest, i.e. the likely rollback targets.
KEEP_YAPPED="${KEEP_YAPPED:-2}"

say() { printf '%s\n' "$*"; }
run() {
    if [ "$APPLY" = 1 ]; then
        say "+ $*"
        "$@"
    else
        say "would run: $*"
    fi
}

[ "$(id -u)" = 0 ] || { say "run as root"; exit 1; }

say "== free space before"
df -h / | tail -1

# Image ids any container refers to, running or not.
in_use="$(docker ps -a --format '{{.Image}}' | xargs -r docker image inspect -f '{{.Id}}' | sort -u)"

say
say "== yapped images not used by a container, beyond the newest $KEEP_YAPPED of each repository"
for repo in ghcr.io/marvinparanoid/yapped ghcr.io/marvinparanoid/yapped-tools; do
    # Newest first, by creation time.
    docker image ls "$repo" --format '{{.CreatedAt}}\t{{.ID}}\t{{.Repository}}:{{.Tag}}' \
        | sort -r \
        | tail -n +"$((KEEP_YAPPED + 1))" \
        | while IFS="$(printf '\t')" read -r _created id ref; do
            full="$(docker image inspect -f '{{.Id}}' "$id")"
            if printf '%s\n' "$in_use" | grep -qx "$full"; then
                say "keep (in use): $ref"
                continue
            fi
            run docker image rm "$ref"
        done
done

say
say "== stale local builds of yapped (six weeks old, no container)"
for ref in yapped-app:latest yapped-migrate:latest; do
    if docker image inspect "$ref" >/dev/null 2>&1; then
        full="$(docker image inspect -f '{{.Id}}' "$ref")"
        if printf '%s\n' "$in_use" | grep -qx "$full"; then
            say "keep (in use): $ref"
        else
            run docker image rm "$ref"
        fi
    fi
done

say
say "== disabled snap revisions (snapd keeps the previous one of each)"
snap list --all | awk '/disabled/ { print $1, $3 }' | while read -r name revision; do
    run snap remove "$name" --revision="$revision"
done

say
say "== apt's package cache"
run apt-get clean

say
say "Not done here, each a decision of its own (see the report):"
say "  - rotating /var/log/openvpn/openvpn.log (needs a logrotate rule; copytruncate)"
say "  - default log rotation for containers in the docker daemon (restarts every container)"

say
say "== free space after"
df -h / | tail -1

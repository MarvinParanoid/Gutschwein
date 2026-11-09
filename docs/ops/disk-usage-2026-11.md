# Disk usage on the VPS — November 2026

Read-only investigation on 2026-11-09. Nothing was deleted, truncated or pruned. The
server hosts several projects; Gutschwein is a small part of its disk.

## Free space

| Date | Free on `/` (15 GB) |
|---|---|
| ~2026-10-26 | 6.2 GB |
| 2026-11-09 morning | 4.0 GB |
| 2026-11-09 afternoon | 3.7 GB (after the 7ec0e78 image was pulled) |

## Where it goes

| Consumer | Size | Owner | Growing? |
|---|---|---|---|
| Docker (`/var/snap/docker/common/var-lib-docker`), mostly image layers | 5.7 GB | all | **yes — the source** |
| — 18 tags of `yapped-tools` (845 MB each, sharing layers) | ~2.4 GB in three base-layer sets | yapped | +~840 MB whenever its base changes |
| — 18 tags of `yapped` (216 MB each, 45 MB unique) | ~0.8 GB unique | yapped | +45 MB per deploy |
| — `yapped-migrate:latest`, `yapped-app:latest` (local builds, six weeks old, no container) | ~0.85 GB | yapped | no |
| — `postgres:17-alpine` | 0.3 GB | yapped | pulled 3 days ago |
| — Gutschwein: `7ec0e78d2f40` (running) and `f35106f0d938` (`:previous`) | 0.53 GB | Gutschwein | +265 MB per deploy, old ones not removed |
| — container logs (`json-file`) | 22 MB (blocktail 20 MB, no rotation) | blocktail | ~4 MB/week |
| `/usr` | 1.9 GB | system | no |
| `/var/lib/snapd/snaps` | 506 MB, of which ~270 MB disabled revisions | system | per snap refresh |
| `/var/log/openvpn/openvpn.log` | 182 MB, never rotated | openvpn | ~20 MB/month |
| `/var/cache/apt` | 113 MB | system | slowly |
| journald | 82 MB (capped at 500 MB) | system | capped |
| `/root/backups` (services script) | 16 MB | ops | 30 days + monthly forever: ~0.5 MB/day |
| `/root/gutschwein-snapshots` | 3.6 MB | Gutschwein | 5 kept |
| Gutschwein data (`/root/sparschwein/data`) | 4.3 MB | Gutschwein | slowly |

**The growth is yapped's deployments.** In the two weeks between the measurements yapped was
deployed six times, its tools image changed its base twice (843 MB and 674 MB of new
layers), and postgres was re-pulled — about 2.1 GB, plus 265 MB for Gutschwein's 7ec0e78.
Old images are never removed, so every deployment is permanent. At that rate the
remaining 3.7 GB lasts three to four weeks; Gutschwein's `deploy.sh` refuses to deploy
below 1 GB free.

Gutschwein itself is about 0.6 GB: two images and its data. The new local backups
(`data/backups`, 7 × ~3.5 MB) add about 25 MB.

## What can safely go

| Action | Recovers | Risk |
|---|---|---|
| yapped and yapped-tools tags without a container, except the newest two of each | ~1.6 GB (≈ 16 × 45 MB app layers + the oldest 842 MB tools base) | loses rollback to older yapped versions (they were pulled from GHCR; check they are still there) |
| `yapped-migrate:latest`, `yapped-app:latest` (no container, six weeks old) | ~0.85 GB | none known; local builds, rebuildable |
| disabled snap revisions | ~0.27 GB | none; snapd keeps them only for revert |
| `apt-get clean` | ~0.1 GB | none |
| rotate `openvpn.log` | up to ~0.18 GB | none with `copytruncate` |

Expected: **about 2.5–3.0 GB** (Docker's own estimate of unshared layers is 1.9 GB; layers
shared only among the removed tags come on top), back to roughly 6.2–6.7 GB free. The
exact figure is the script's before/after `df`.

## What must stay

- Every image a container uses, running or stopped (`yapped-migrate-1` uses the current
  tools image).
- Gutschwein's running image and `:previous` — the rollback.
- Volumes, the build cache (43 MB, not worth the risk), every database and data directory.
- `/root/backups`, `/root/gutschwein-snapshots`, `/root/yapped-backups`, Gutschwein's
  `data/backups`.

## Prepared, not run

[`disk-cleanup.sh`](disk-cleanup.sh): dry run by default, `--apply` to act. It removes only
images no container uses, keeps the newest two of each yapped repository and never touches
Gutschwein's images, volumes or data. **It changes other projects' state**, so it needs
their owner's agreement. No `docker system prune` anywhere: that takes whatever is unused at
the moment, rollback images included.

## Proposed retention

- **Each project's deploy removes its own old images**, keeping the current and one
  previous. For Gutschwein: after a healthy deploy, remove images older than `:previous`
  (a small addition to `deploy.sh`, not made yet — a decision of its own).
- **Container logs**: `json-file` with `max-size: 10m, max-file: 3` as the daemon default.
  Changing `daemon.json` restarts every container on the server, so it needs a window;
  Gutschwein and nebenbei set it per container already.
- **openvpn.log**: a logrotate rule — weekly, keep 4, compress, `copytruncate`.
- **apt and snap**: `apt-get clean` monthly; snap keeps one previous revision (its default).
- **Backups**: unchanged — the services script's 30 days plus monthly, deploy snapshots ×5,
  Gutschwein's local archives ×7.
- **Alert**: below 2 GB free, which today nobody would notice; Gutschwein's deploy stops
  at 1 GB.

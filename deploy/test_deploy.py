"""deploy.sh, run for real against a throwaway directory.

Everything the script does on the host is real here — the lock, git, df, the
SQLite backup, the copy of the pictures. Docker and curl are stand-ins that keep
their state in a JSON file and can be told to fail, so a broken pull or a dead
container can be staged without a daemon.

    backend/.venv/bin/python -m pytest deploy/
"""

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "deploy.sh"
SHELL = os.environ.get("DEPLOY_TEST_SHELL", "sh")
IMAGE = "ghcr.io/marvinparanoid/gutschwein"
OLD, NEW, NEWER = "sha256:" + "0" * 64, "sha256:" + "a" * 64, "sha256:" + "b" * 64
TAG_NEW, TAG_NEWER = "aaaaaaaaaaaa", "bbbbbbbbbbbb"

FAKE_DOCKER = r"""#!/usr/bin/env python3
import json, os, sys, time
STATE = os.environ["FAKE_STATE"]
IMAGE = "ghcr.io/marvinparanoid/gutschwein"
s = json.load(open(STATE))
s["log"].append(" ".join(sys.argv[1:]))
# Which deployment made the call, for the tests that run two at once.
s.setdefault("callers", []).append(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
args = sys.argv[1:]

def save():
    # Atomically: the tests read this file while a deployment is running.
    with open(STATE + ".tmp", "w") as f:
        json.dump(s, f)
    os.replace(STATE + ".tmp", STATE)

def resolve(ref):
    if ref in s["images"]:
        return ref
    for image_id, meta in s["images"].items():
        if ref in meta["tags"]:
            return image_id
    return None

def untag(ref):
    for meta in s["images"].values():
        if ref in meta["tags"]:
            meta["tags"].remove(ref)

def unused(image_id):
    c = s["container"]
    return not s["images"][image_id]["tags"] and not (c and c["image"] == image_id)

out, code = "", 0
if args[:1] == ["pull"]:
    ref = args[-1]
    time.sleep(s.get("pull_sleep", 0))
    image_id = s["registry"].get(ref.split(":")[-1])
    if image_id is None:
        code = 1
    else:
        untag(ref)
        s["images"].setdefault(image_id, {"tags": [], "created": s["created"].get(image_id, "2026-01-01 00:00:00")})
        s["images"][image_id]["tags"].append(ref)
elif args[:2] == ["image", "inspect"]:
    image_id = resolve(args[-1])
    out, code = (image_id, 0) if image_id else ("", 1)
elif args[:1] == ["run"]:
    code = 1 if resolve(args[-3]) in s.get("broken", []) else 0
elif args[:1] == ["tag"]:
    image_id = resolve(args[1])
    untag(args[2])
    s["images"][image_id]["tags"].append(args[2])
elif args[:1] == ["inspect"]:
    c = s["container"]
    if not c:
        code = 1
    elif "Health" in args[2]:
        out = f"{c['image']} {'healthy' if c['healthy'] else 'unhealthy'}"
    else:
        out = c["image"]
elif args[:1] == ["info"]:
    out = s["docker_root"]
elif args[:1] == ["images"]:
    out = "\n".join(
        f"{meta['created']}|{tag.split(':', 1)[1]}"
        for meta in s["images"].values() for tag in meta["tags"] if tag.startswith(IMAGE + ":")
    )
elif args[:1] == ["rmi"]:
    image_id = resolve(args[-1])
    untag(args[-1])
    if image_id and unused(image_id):
        del s["images"][image_id]
elif args[:2] == ["image", "prune"]:
    for image_id in [i for i in s["images"] if unused(i)]:
        del s["images"][image_id]
elif args[:2] == ["builder", "prune"]:
    pass
elif args[:1] == ["compose"]:
    sub = args[1]
    c = s["container"]
    if sub == "ps":
        out = (c["id"] if c and c["running"] else "") if "-q" in args else "app"
    elif sub == "stop":
        c["running"] = False
        save()  # stopped from here on, whatever happens while it "takes time"
        time.sleep(s.get("stop_sleep", 0))
    elif sub == "start":
        c["running"] = True
    elif sub == "up":
        if s.get("up_fails"):
            code = 1
        else:
            image_id = resolve(f"{IMAGE}:{os.environ['GUTSCHWEIN_TAG']}")
            s["container"] = {
                "id": f"c{len(s['log'])}", "image": image_id, "running": True,
                "healthy": s.get("health", True),
            }
    elif sub == "logs":
        out = "app | (logs)"
else:
    sys.exit(f"fake docker: unhandled {args}")
save()
if out:
    print(out)
sys.exit(code)
"""

FAKE_CURL = r"""#!/usr/bin/env python3
import json, os, sys
s = json.load(open(os.environ["FAKE_STATE"]))
c = s["container"]
ok = bool(c and c["running"] and c["healthy"])
print('{"status":"ok"}' if ok else "", end="")
sys.exit(0 if ok else 7)
"""


class Host:
    """A deployment directory, a git remote, and the fake Docker's state."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dir = root / "sparschwein"
        self.data = self.dir / "data"
        self.state_file = root / "docker.json"
        # Where production keeps them: beside the checkout, never inside it.
        self.snapshot_root = root / "gutschwein-snapshots"
        self.lock = root / "lock" / "deploy.lock"
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
            path = self.bin / name
            path.write_text(body.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
            path.chmod(0o755)

        remote = root / "remote.git"
        work = root / "work"
        for command in (
            ["git", "init", "-q", "-b", "main", str(work)],
            [
                "git",
                "-C",
                str(work),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "release",
            ],
            ["git", "clone", "-q", "--bare", str(work), str(remote)],
            ["git", "init", "-q", "-b", "main", str(self.dir)],
            ["git", "-C", str(self.dir), "remote", "add", "origin", f"file://{remote}"],
        ):
            subprocess.run(command, check=True)
        (self.dir / ".env").write_text("DEV_MODE=false\n")
        (self.data / "uploads" / "2026-10").mkdir(parents=True)
        self.state = {
            "registry": {TAG_NEW: NEW, TAG_NEWER: NEWER},
            "created": {NEW: "2026-10-01 10:00:00", NEWER: "2026-10-02 10:00:00"},
            "images": {
                OLD: {
                    "tags": [f"{IMAGE}:000000000000"],
                    "created": "2026-09-01 10:00:00",
                }
            },
            "container": {
                "id": "c-old",
                "image": OLD,
                "running": True,
                "healthy": True,
            },
            "docker_root": str(root),
            "log": [],
        }
        self.save()

    def save(self) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.state_file)

    def load(self) -> dict:
        self.state = json.loads(self.state_file.read_text())
        return self.state

    def env(self, **extra: str) -> dict:
        return {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_STATE": str(self.state_file),
            "DEPLOY_DIR": str(self.dir),
            "DEPLOY_SNAPSHOTS": str(self.snapshot_root),
            "DEPLOY_LOCK": str(self.lock),
            "DEPLOY_MIN_FREE_MB": "1",
            "DEPLOY_HEALTH_TRIES": "2",
            "DEPLOY_HEALTH_DELAY": "0",
            **extra,
        }

    def deploy(self, command: str = f"deploy {TAG_NEW}", **extra: str):
        # Not check=True: a refused deployment is what half of these tests expect.
        return subprocess.run(
            [SHELL, str(SCRIPT)],
            check=False,
            env=self.env(SSH_ORIGINAL_COMMAND=command, **extra),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def snapshots(self) -> list[Path]:
        root = self.snapshot_root
        return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []

    def start(self, command: str = f"deploy {TAG_NEW}", **extra: str) -> subprocess.Popen:
        return subprocess.Popen(
            [SHELL, str(SCRIPT)],
            env=self.env(SSH_ORIGINAL_COMMAND=command, **extra),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def wait_for(self, entry: str) -> None:
        deadline = time.time() + 10
        while entry not in self.load()["log"]:
            assert time.time() < deadline, f"never reached: {entry}"
            time.sleep(0.02)

    def tags(self, image_id: str) -> list[str]:
        return self.load()["images"].get(image_id, {}).get("tags", [])


def _database(path: Path, rows: int = 3) -> None:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE alembic_version (version_num TEXT)")
    db.execute("INSERT INTO alembic_version VALUES ('0011')")
    db.execute("CREATE TABLE vouchers (id INTEGER PRIMARY KEY, merchant TEXT)")
    db.executemany(
        "INSERT INTO vouchers (merchant) VALUES (?)",
        [(f"Synth{i}",) for i in range(rows)],
    )
    db.commit()
    db.close()


@pytest.fixture
def host(tmp_path: Path) -> Host:
    h = Host(tmp_path)
    _database(h.data / "gutschwein.db")
    for name in ("a" * 32, "b" * 32):
        (h.data / "uploads" / "2026-10" / f"{name}.webp").write_bytes(os.urandom(2048))
    return h


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _meta(snapshot: Path) -> dict:
    return dict(line.split("=", 1) for line in (snapshot / "snapshot.txt").read_text().splitlines())


# --- the path that works ----------------------------------------------------------


def test_a_deploy_snapshots_switches_and_keeps_the_old_image(host: Host) -> None:
    result = host.deploy()

    assert result.returncode == 0, result.stderr
    state = host.load()
    assert state["container"]["image"] == NEW and state["container"]["running"]
    assert f"{IMAGE}:previous" in host.tags(OLD)
    (snapshot,) = host.snapshots()
    assert snapshot.name.endswith(f"-{TAG_NEW}")
    meta = _meta(snapshot)
    assert (meta["from_image"], meta["to_tag"], meta["to_image"]) == (OLD, TAG_NEW, NEW)
    assert meta["alembic_version"] == "0011" and meta["rows_vouchers"] == "3"
    assert meta["db_sha256"] == _sha(snapshot / "gutschwein.db")
    assert meta["uploads_files"] == "2"
    # The app was stopped before the snapshot and the new one started after it.
    log = state["log"]
    assert log.index("compose stop app") < log.index("compose up -d")
    assert oct(host.snapshot_root.stat().st_mode)[-3:] == "700"
    assert not (host.snapshot_root / "in-progress").exists()


# --- nothing is touched when preflight fails -------------------------------------


def _untouched(host: Host, result) -> None:
    assert result.returncode != 0
    state = host.load()
    assert state["container"] == {
        "id": "c-old",
        "image": OLD,
        "running": True,
        "healthy": True,
    }
    assert not any(entry.startswith("compose stop") for entry in state["log"])
    assert host.snapshots() == []


def test_an_image_that_cannot_be_pulled_stops_nothing(host: Host) -> None:
    result = host.deploy("deploy cccccccccccc")

    _untouched(host, result)
    assert "не удалось скачать" in result.stderr


def test_an_image_that_does_not_start_stops_nothing(host: Host) -> None:
    host.state["broken"] = [NEW]
    host.save()

    result = host.deploy()

    _untouched(host, result)
    assert "не проходит проверку импорта" in result.stderr


def test_too_little_disk_stops_nothing(host: Host) -> None:
    result = host.deploy(DEPLOY_MIN_FREE_MB=str(10**9))

    _untouched(host, result)
    assert "мало места" in result.stderr
    assert not any(entry.startswith("pull") for entry in host.load()["log"])


@pytest.mark.parametrize(
    "command",
    [
        "deploy aaaa",
        "deploy AAAAAAAAAAAA",
        "deploy aaaaaaaaaaaa;id",
        "deploy aaaaaaaaaaaa\nid",
        "drop",
    ],
)
def test_a_malformed_command_is_refused_before_anything(host: Host, command: str) -> None:
    result = host.deploy(command)

    _untouched(host, result)
    assert host.load()["log"] == []


# --- one at a time ----------------------------------------------------------------------


def test_a_second_deploy_waits_for_nobody_and_touches_nothing(host: Host) -> None:
    host.state["pull_sleep"] = 3
    host.save()
    first = host.start()
    deadline = time.time() + 10
    while not any(e.startswith("pull") for e in host.load()["log"]):
        assert time.time() < deadline
        time.sleep(0.05)

    second = host.deploy(f"deploy {TAG_NEWER}")

    assert second.returncode != 0
    assert "уже идёт другой деплой" in second.stderr
    assert first.wait(timeout=30) == 0
    # Not one docker call came from the second run, whatever the first did meanwhile.
    assert f"deploy {TAG_NEWER}" not in host.load()["callers"]
    assert host.load()["container"]["image"] == NEW


# --- the snapshot -------------------------------------------------------------------------


def test_committed_transactions_still_in_the_wal_are_in_the_snapshot(
    host: Host,
) -> None:
    """A writer that died without checkpointing leaves its commits in -wal only."""
    database = host.data / "gutschwein.db"
    code = (
        "import os, sqlite3, sys\n"
        "db = sqlite3.connect(sys.argv[1])\n"
        "db.execute('PRAGMA wal_autocheckpoint=0')\n"
        "db.executemany('INSERT INTO vouchers (merchant) VALUES (?)', [('Wal',)] * 50)\n"
        "db.commit()\n"
        "os._exit(0)  # no close, no checkpoint\n"
    )
    subprocess.run([sys.executable, "-c", code, str(database)], check=True)
    assert Path(f"{database}-wal").stat().st_size > 0
    # The main file on its own does not have them yet.
    alone = host.root / "alone.db"
    alone.write_bytes(database.read_bytes())
    assert sqlite3.connect(alone).execute("SELECT count(*) FROM vouchers").fetchone()[0] == 3

    assert host.deploy().returncode == 0

    (snapshot,) = host.snapshots()
    copy = sqlite3.connect(snapshot / "gutschwein.db")
    assert copy.execute("SELECT count(*) FROM vouchers").fetchone()[0] == 53
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not Path(f"{snapshot / 'gutschwein.db'}-wal").exists()


def test_the_pictures_are_an_independent_copy(host: Host) -> None:
    assert host.deploy().returncode == 0
    (snapshot,) = host.snapshots()
    for live in (host.data / "uploads").rglob("*.webp"):
        copied = snapshot / "uploads" / live.relative_to(host.data / "uploads")
        assert _sha(copied) == _sha(live)
        assert copied.stat().st_ino != live.stat().st_ino
        before = _sha(copied)
        live.write_bytes(b"changed afterwards")
        assert _sha(copied) == before


@pytest.mark.parametrize("damage", ["unreadable-db", "corrupt-db", "unreadable-picture"])
def test_a_failed_snapshot_is_removed_and_the_old_app_resumes(host: Host, damage: str) -> None:
    if damage == "unreadable-db":
        (host.data / "gutschwein.db").chmod(0)
    elif damage == "corrupt-db":
        for suffix in ("-wal", "-shm"):
            Path(f"{host.data / 'gutschwein.db'}{suffix}").unlink(missing_ok=True)
        (host.data / "gutschwein.db").write_bytes(b"SQLite format 3\x00" + os.urandom(4096))
    else:
        next((host.data / "uploads").rglob("*.webp")).chmod(0)

    result = host.deploy()

    assert result.returncode != 0
    assert "снимок" in result.stderr or "картин" in result.stderr
    assert "незавершённый снимок удалён" in result.stdout
    assert "возвращаю прежний контейнер" in result.stdout
    state = host.load()
    assert state["container"] == {
        "id": "c-old",
        "image": OLD,
        "running": True,
        "healthy": True,
    }
    assert not any(entry.startswith("compose up") for entry in state["log"])
    assert host.snapshots() == []


def test_a_snapshot_left_half_done_by_a_killed_run_is_cleared(host: Host) -> None:
    stale = host.snapshot_root / "20260101T000000Z-aaaaaaaaaaaa.partial"
    stale.mkdir(parents=True)
    (stale / "gutschwein.db").write_bytes(b"half")

    assert host.deploy().returncode == 0

    assert not stale.exists()
    assert all(not p.name.endswith(".partial") for p in host.snapshots())


def test_old_snapshots_are_pruned_to_the_newest_few(host: Host) -> None:
    root = host.snapshot_root
    root.mkdir()
    for day in range(1, 7):
        (root / f"202601{day:02d}T000000Z-aaaaaaaaaaaa").mkdir()
    (root / "notes").mkdir()  # not a snapshot: retention must not count or remove it

    assert host.deploy(DEPLOY_KEEP_SNAPSHOTS="3").returncode == 0

    names = [p.name for p in host.snapshots()]
    assert "notes" in names
    names.remove("notes")
    assert len(names) == 3
    assert names[-1].endswith(f"-{TAG_NEW}") and "20260105T000000Z-aaaaaaaaaaaa" in names


# --- the rollback candidate -----------------------------------------------------------


def test_the_previous_image_survives_pruning_across_releases(host: Host) -> None:
    assert host.deploy().returncode == 0
    assert f"{IMAGE}:previous" in host.tags(OLD)

    assert host.deploy(f"deploy {TAG_NEWER}").returncode == 0

    # :previous moved to what was running; the image before that may go, the
    # rollback candidate may not — even though nothing else names it now.
    assert f"{IMAGE}:previous" in host.tags(NEW)
    assert host.load()["container"]["image"] == NEWER
    assert NEW in host.load()["images"]


def test_the_previous_image_is_kept_even_when_it_is_the_oldest(host: Host) -> None:
    """Retention keeps the two newest release tags; the rollback candidate is kept
    by name on top of those, however old it is."""
    for tag, created in (
        ("dddddddddddd", "2026-10-05 10:00:00"),
        ("eeeeeeeeeeee", "2026-10-06 10:00:00"),
    ):
        host.state["images"][f"sha256:{tag[0] * 64}"] = {
            "tags": [f"{IMAGE}:{tag}"],
            "created": created,
        }
    host.save()

    assert host.deploy().returncode == 0

    assert f"{IMAGE}:previous" in host.tags(OLD)
    assert f"{IMAGE}:000000000000" not in host.tags(OLD)  # its release tag did go


def test_redeploying_the_running_image_keeps_it(host: Host) -> None:
    assert host.deploy().returncode == 0
    assert host.deploy().returncode == 0
    assert host.load()["container"]["image"] == NEW
    assert f"{IMAGE}:previous" in host.tags(NEW)


# --- after the switch nothing is undone automatically ------------------------------


def test_a_new_version_that_never_answers_is_reported_not_rolled_back(
    host: Host,
) -> None:
    host.state["health"] = False
    host.save()

    result = host.deploy()

    assert result.returncode != 0
    assert "Ничего не откатывается автоматически" in result.stdout
    assert ":previous" in result.stdout and "snapshots/" in result.stdout
    state = host.load()
    assert state["container"]["image"] == NEW  # left as it is for a person to decide
    assert not any(entry == "compose start app" for entry in state["log"])
    assert len(host.snapshots()) == 1
    # The outcome is unclear, so the note stays — and holds the next deployment back
    # until a person has looked and moved it aside.
    note = host.snapshot_root / "in-progress"
    assert "stage=health" in note.read_text()
    host.state = host.load()
    host.state["health"] = True
    host.save()
    assert host.deploy(f"deploy {TAG_NEWER}").returncode != 0
    note.rename(host.snapshot_root / "in-progress.reviewed-test")
    assert host.deploy(f"deploy {TAG_NEWER}").returncode == 0
    assert not note.exists()
    assert (host.snapshot_root / "in-progress.reviewed-test").exists()  # evidence kept


def test_a_failed_switch_does_not_start_anything_on_its_own(host: Host) -> None:
    host.state["up_fails"] = True
    host.save()

    result = host.deploy()

    assert result.returncode != 0
    assert "новый контейнер не создан" in result.stderr
    assert not any(entry == "compose start app" for entry in host.load()["log"])
    assert len(host.snapshots()) == 1
    assert "stage=switching" in (host.snapshot_root / "in-progress").read_text()


# --- the last known-good image ------------------------------------------------------


def test_a_failed_deployment_does_not_become_the_rollback_candidate(host: Host) -> None:
    host.state["health"] = False
    host.save()
    failed = host.deploy()
    assert failed.returncode != 0
    assert host.load()["container"]["image"] == NEW  # the failed version is what runs now
    # Someone looked at it, found the database fine, and moved the note aside.
    (host.snapshot_root / "in-progress").rename(host.snapshot_root / "in-progress.reviewed")

    host.state["health"] = True
    host.save()
    retry = host.deploy(f"deploy {TAG_NEWER}")

    assert retry.returncode == 0, retry.stderr
    assert "не healthy" in retry.stdout
    # The candidate is still the last version that was healthy, not the failed one.
    assert f"{IMAGE}:previous" in host.tags(OLD)
    assert f"{IMAGE}:previous" not in host.tags(NEW)
    assert _meta(host.snapshots()[-1])["from_state"] == "unhealthy"


def test_the_rollback_candidate_is_the_running_image_not_latest(host: Host) -> None:
    """:latest may name something that never ran here; the candidate is what did."""
    host.state["images"][NEWER] = {
        "tags": [f"{IMAGE}:latest"],
        "created": "2026-10-02 10:00:00",
    }
    host.save()

    assert host.deploy().returncode == 0

    assert f"{IMAGE}:previous" in host.tags(OLD)
    assert f"{IMAGE}:previous" not in host.tags(NEWER)


# --- interruptions --------------------------------------------------------------------


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGINT", "SIGHUP"])
def test_an_interruption_after_the_stop_starts_the_old_app_again(host: Host, signal_name) -> None:
    """SIGHUP is what a dropped ssh session sends; dash would die without cleanup."""
    host.state["stop_sleep"] = 1
    host.save()
    run = host.start()
    host.wait_for("compose stop app")

    run.send_signal(getattr(signal, signal_name))
    out, _err = run.communicate(timeout=30)

    assert run.returncode != 0
    assert "возвращаю прежний контейнер" in out
    state = host.load()
    assert state["container"] == {
        "id": "c-old",
        "image": OLD,
        "running": True,
        "healthy": True,
    }
    assert not any(entry.startswith("compose up") for entry in state["log"])
    assert not any(p.name.endswith(".partial") for p in host.snapshot_root.iterdir())
    assert not (host.snapshot_root / "in-progress").exists()


def test_a_client_that_goes_away_after_the_stop_does_not_leave_the_app_down(
    host: Host,
) -> None:
    """Whoever reads the output stops after three lines — the app is stopped by then.
    The next line fails to write; the run ends and the old app is started again."""
    run = subprocess.Popen(
        f'"{SHELL}" "{SCRIPT}" | head -n 3',
        shell=True,
        env=host.env(SSH_ORIGINAL_COMMAND=f"deploy {TAG_NEW}"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    run.communicate(timeout=30)
    deadline = time.time() + 10
    while (host.snapshot_root / "in-progress").exists():  # the script outlives `head`
        assert time.time() < deadline
        time.sleep(0.05)

    state = host.load()
    assert "compose stop app" in state["log"]
    assert not any(entry.startswith("compose up") for entry in state["log"])
    assert state["container"] == {
        "id": "c-old",
        "image": OLD,
        "running": True,
        "healthy": True,
    }


def test_a_run_killed_outright_leaves_a_note_and_the_next_one_recovers(
    host: Host,
) -> None:
    host.state["stop_sleep"] = 1
    host.save()
    run = host.start()
    host.wait_for("compose stop app")
    time.sleep(0.2)
    run.send_signal(signal.SIGKILL)
    run.communicate(timeout=30)

    # No cleanup could run: the app is down, and the note says where it stopped.
    assert host.load()["container"]["running"] is False
    note = (host.snapshot_root / "in-progress").read_text()
    assert "stage=stopping-old" in note and f"old_image={OLD}" in note
    report = host.deploy("dry-run")
    assert "ПРЕРВАННЫЙ ДЕПЛОЙ" in report.stdout and "stage=stopping-old" in report.stdout

    host.state = host.load()
    host.state["stop_sleep"] = 0
    host.save()
    retry = host.deploy()

    assert retry.returncode == 0, retry.stderr
    assert "предыдущий деплой был прерван" in retry.stdout
    assert host.load()["container"]["image"] == NEW
    assert f"{IMAGE}:previous" in host.tags(OLD)  # tagged before the kill, and kept
    assert not (host.snapshot_root / "in-progress").exists()


# --- snapshots and git ------------------------------------------------------------------


def test_snapshots_live_outside_the_checkout_and_survive_git(host: Host) -> None:
    assert host.deploy().returncode == 0
    (snapshot,) = host.snapshots()
    assert not snapshot.resolve().is_relative_to(host.dir.resolve())
    before = _sha(snapshot / "gutschwein.db")

    for command in (
        ["reset", "-q", "--hard", "HEAD"],
        ["clean", "-q", "-ffdx"],
        ["checkout", "-q", "-B", "main", "origin/main"],
    ):
        subprocess.run(["git", "-C", str(host.dir), *command], check=True)
    # clean -x takes every untracked file in the checkout — on the server that is
    # .env and data/ too. The snapshots are elsewhere; .env is put back to go on.
    assert not (host.dir / ".env").exists()
    (host.dir / ".env").write_text("DEV_MODE=false\n")
    # A deployment resets the checkout once more.
    assert host.deploy(f"deploy {TAG_NEWER}").returncode == 0

    assert snapshot.is_dir()
    assert _sha(snapshot / "gutschwein.db") == before


# --- CI ---------------------------------------------------------------------------------


def test_ci_runs_these_tests_under_dash() -> None:
    """The server's /bin/sh is dash; CI must run this suite with it, and shellcheck."""
    ci = (HERE.parent / ".github" / "workflows" / "ci.yml").read_text()
    job = ci[ci.index("\n  deploy-script:") :]
    assert "DEPLOY_TEST_SHELL: dash" in job
    assert "pytest" in job and "deploy/" in job
    assert "shellcheck -s sh deploy/deploy.sh" in job


# --- a note from after the switch holds deployments back ------------------------------


def _tree(*roots: Path) -> dict:
    """Every path under the roots with its type, mode, size, mtime and content hash."""
    seen = {}
    for root in roots:
        for path in sorted([root, *root.rglob("*")]):
            st = path.lstat()
            digest = _sha(path) if path.is_file() and not path.is_symlink() else None
            seen[str(path)] = (st.st_mode, st.st_size, st.st_mtime_ns, digest)
    return seen


def _docker(host: Host) -> dict:
    """The fake Docker's images and container, without its own call log."""
    state = host.load()
    return {"images": state["images"], "container": state["container"]}


@pytest.mark.parametrize("stage", ["switching", "health", "something-else", None])
def test_a_note_from_after_the_switch_stops_the_next_deployment(host: Host, stage) -> None:
    note = host.snapshot_root / "in-progress"
    host.snapshot_root.mkdir()
    body = (f"stage={stage}\n" if stage else "") + "since=2026-10-25T22:00:00Z\ntag=aaaaaaaaaaaa\n"
    note.write_text(body)
    before = (_tree(host.dir, host.snapshot_root), _docker(host))

    result = host.deploy(f"deploy {TAG_NEWER}")

    assert result.returncode != 0
    assert "частично мигрированной" in result.stderr and "mv " in result.stderr
    assert note.read_text() == body  # the evidence is untouched
    assert (_tree(host.dir, host.snapshot_root), _docker(host)) == before
    assert host.load()["log"] == []  # not one docker call


@pytest.mark.parametrize("stage", ["preflight", "stopping-old", "snapshot"])
def test_a_note_from_before_the_switch_lets_the_next_deployment_go_on(host: Host, stage) -> None:
    host.snapshot_root.mkdir()
    (host.snapshot_root / "in-progress").write_text(f"stage={stage}\n")

    result = host.deploy()

    assert result.returncode == 0, result.stderr
    assert "база не менялась" in result.stdout
    assert not (host.snapshot_root / "in-progress").exists()


# --- dry-run --------------------------------------------------------------------------


def test_dry_run_changes_nothing_at_all(host: Host) -> None:
    """With every kind of state present: a complete and a partial snapshot, a note,
    a rollback candidate, a stopped container."""
    assert host.deploy().returncode == 0
    (host.snapshot_root / "20260101T000000Z-aaaaaaaaaaaa.partial").mkdir()
    (host.snapshot_root / "in-progress").write_text("stage=switching\n")
    host.state = host.load()
    host.state["container"]["running"] = False
    host.state["log"] = []
    host.save()
    host.lock.parent.mkdir(exist_ok=True)
    git_before = (
        subprocess.run(
            ["git", "-C", str(host.dir), "status", "--porcelain", "--ignored"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        + subprocess.run(
            ["git", "-C", str(host.dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    before = (_tree(host.dir, host.snapshot_root, host.lock.parent), _docker(host))

    result = host.deploy("dry-run")

    assert result.returncode == 0, result.stderr
    assert "ПРЕРВАННЫЙ ДЕПЛОЙ" in result.stdout and "stage=switching" in result.stdout
    assert (_tree(host.dir, host.snapshot_root, host.lock.parent), _docker(host)) == before
    git_after = (
        subprocess.run(
            ["git", "-C", str(host.dir), "status", "--porcelain", "--ignored"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        + subprocess.run(
            ["git", "-C", str(host.dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert git_after == git_before
    # Only questions were asked of Docker.
    for call in host.load()["log"]:
        assert call.split()[0] in ("inspect", "image", "compose"), call
        assert call.startswith(("inspect", "image inspect", "compose ps")), call


def test_dry_run_works_while_a_deployment_holds_the_lock(host: Host) -> None:
    host.state["pull_sleep"] = 3
    host.save()
    first = host.start()
    host.wait_for(f"pull -q {IMAGE}:{TAG_NEW}")

    report = host.deploy("dry-run")

    assert report.returncode == 0
    assert "stage=preflight" in report.stdout  # it sees the running deployment's note
    assert first.wait(timeout=30) == 0

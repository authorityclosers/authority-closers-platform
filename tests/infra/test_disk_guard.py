"""Disk guard: exercise decisions against sandbox paths and fake destructive commands."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-disk-guard"
SERVICE = ROOT / "infra/application/systemd/ac-disk-guard.service"
TIMER = ROOT / "infra/application/systemd/ac-disk-guard.timer"
CONF = ROOT / "infra/application/config/ac-disk-guard.conf.example"
GIB = 1024**3

# rm deliberately records requests WITHOUT unlinking anything, even in the sandbox.
FAKE = """
import json, os, pathlib, re, sys
root = pathlib.Path(sys.argv[0]).parent.parent
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "id":
    print(os.getuid())
elif name == "df":
    count = root / "df-count"
    n = int(count.read_text()) if count.exists() else 0
    count.write_text(str(n + 1))
    sequence = os.environ.get("FAKE_FREE", "7").split(",")
    value = sequence[min(n, len(sequence) - 1)]
    print("Avail")
    print(int(value) * 1024**3 if value.isdigit() else value)
elif name == "pgrep":
    process = os.environ.get("FAKE_PROCESS", "")
    if process:
        pattern = args[-1].replace("[[:space:]]", "[ " + chr(9) + "]")
        sys.exit(0 if re.search(pattern, process) else 1)
    sys.exit(int(os.environ.get("FAKE_PGREP", "1")))
elif name == "du":
    print("4096\\t" + args[-1])
elif name == "docker" and args[:2] == ["image", "ls"]:
    if not (root / "pruned").exists():
        print("sha256:example 1GB")
elif name == "docker":
    if args[:2] == ["image", "prune"] and not os.environ.get("FAKE_FAIL"):
        (root / "pruned").touch()
    print("Deleted: sha256:example; reclaimed 1GB")
    sys.exit(1 if os.environ.get("FAKE_FAIL") == "docker" else 0)
elif name == "ac-release":
    sys.exit(1) if os.environ.get("FAKE_FAIL") == name else None
    print('{"removed": ["artifacts/example"], "artifacts": [{"bytes": 4096}]}')
elif name == "journalctl":
    sys.exit(1) if os.environ.get("FAKE_FAIL") == name else None
    print("Deleted archived journal /fake/journal (1M)")
elif name == "apt-get":
    sys.exit(1) if os.environ.get("FAKE_FAIL") == name else None
elif name == "rm":
    if os.environ.get("FAKE_FAIL") == "rm" and "--one-file-system" in args:
        sys.exit(1)
elif name == "ac-archive-put":
    print("untrusted provider output must not reach guard logs")
    sys.exit(1 if os.environ.get("FAKE_FAIL") == name else 0)
"""


@pytest.fixture
def guard(tmp_path: Path) -> Path:
    (tmp_path / "bin").mkdir()
    for name in [
        "df",
        "docker",
        "journalctl",
        "apt-get",
        "ac-release",
        "pgrep",
        "rm",
        "du",
        "id",
        "ac-archive-put",
    ]:
        path = tmp_path / "bin" / name
        path.write_text(f"#!{sys.executable}\n{FAKE}")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    for path in ["src", "tmp", "work", "paperclip", "backups"]:
        (tmp_path / path).mkdir()
    return tmp_path


def _run(
    root: Path,
    *,
    config: str = "",
    free: str = "7",
    pgrep: int = 1,
    fail: str = "",
    process: str = "",
) -> subprocess.CompletedProcess[str]:
    (root / "conf").write_text(config)
    env = dict(os.environ)
    # No destructive operation can reach the real host, regardless of PATH contents.
    env.update(
        AC_DISK_CONF=str(root / "conf"),
        AC_DISK_LOG=str(root / "guard.log"),
        AC_DISK_ALERT=str(root / "metrics" / "disk-alert.json"),
        AC_DISK_LOCK=str(root / "lock"),
        AC_DISK_SRC=str(root / "src"),
        AC_DISK_TMP=str(root / "tmp"),
        AC_DISK_WORK=str(root / "work"),
        AC_DISK_PAPERCLIP=str(root / "paperclip"),
        AC_DISK_APT_CACHE=str(root / "apt-cache"),
        AC_DISK_BACKUPS=str(root / "backups"),
        AC_DISK_CUT=str(root / "cut"),
        AC_DISK_PYTHON=sys.executable,
        PATH=f"{root / 'bin'}:{os.environ.get('PATH', '')}",
        FAKE_FREE=free,
        FAKE_PGREP=str(pgrep),
        FAKE_FAIL=fail,
        FAKE_PROCESS=process,
    )
    for key, command in {
        "DF": "df",
        "DOCKER": "docker",
        "JOURNAL": "journalctl",
        "APT": "apt-get",
        "RELEASE": "ac-release",
        "PGREP": "pgrep",
        "RM": "rm",
        "DU": "du",
        "ARCHIVE": "ac-archive-put",
    }.items():
        env[f"AC_DISK_{key}"] = str(root / "bin" / command)
    return subprocess.run(  # noqa: S603
        ["/bin/bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _calls(root: Path, name: str | None = None) -> list[list[str]]:
    path = root / "calls"
    calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [c for c in calls if c[0] == name] if name else calls


def _removed(root: Path) -> set[Path]:
    return {Path(c[-1]) for c in _calls(root, "rm") if "--one-file-system" in c}


def _file(root: Path, name: str, *, hours: int = 100) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("DO NOT LOG THESE CONTENTS")
    when = time.time() - hours * 3600
    os.utime(path, (when, when))
    return path


def _directory(root: Path, name: str, *, hours: int = 100) -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    when = time.time() - hours * 3600
    os.utime(path, (when, when))
    return path


@pytest.mark.parametrize("free", ["90", "100"])
def test_target_already_met_logs_inventory_without_cleanup(guard: Path, free: str) -> None:
    result = _run(guard, free=free)
    assert result.returncode == 0, result.stderr
    assert [c[0] for c in _calls(guard)] == ["df"]
    assert len((guard / "guard.log").read_text().splitlines()) == 2


def test_config_target_and_early_stop_after_first_step(guard: Path) -> None:
    result = _run(guard, config="TARGET_FREE_GB=50\n", free="7,50")
    assert result.returncode == 0, result.stderr
    assert [c for c in _calls(guard, "docker") if "prune" in c] == [
        ["docker", "image", "prune", "-f"]
    ]
    assert not _calls(guard, "journalctl")
    log = (guard / "guard.log").read_text()
    assert f"before_free_bytes={7 * GIB}" in log
    assert f"after_free_bytes={50 * GIB} status=0" in log
    assert "sha256:example" in log and "1GB" in log
    assert not (guard / "metrics" / "disk-alert.json").exists()


def test_tier_one_order_failures_and_critical_alert(guard: Path) -> None:
    result = _run(guard, fail="docker")
    assert result.returncode == 0, result.stderr
    calls = [c for c in _calls(guard) if c[0] not in {"df", "pgrep", "rm", "id"} and "ls" not in c]
    assert calls == [
        ["docker", "image", "prune", "-f"],
        ["docker", "builder", "prune", "-f"],
        ["journalctl", "--vacuum-size=300M"],
        ["apt-get", "clean"],
        ["ac-release", "prune-artifacts", "--apply", "--keep-recent", "3", "--json"],
    ]
    alert = json.loads((guard / "metrics" / "disk-alert.json").read_text())
    assert stat.S_IMODE((guard / "metrics" / "disk-alert.json").stat().st_mode) == 0o644
    assert stat.S_IMODE((guard / "metrics").stat().st_mode) == 0o755
    assert alert["free_gb"] == 7
    assert alert["tried"] == [
        "docker-images",
        "docker-builder",
        "journal",
        "apt",
        "release-artifacts",
        "source-caches",
        "temporary-files",
    ]
    assert "T" in alert["time"]
    assert "step=docker-images after_free_bytes=" in (guard / "guard.log").read_text()
    assert "status=1" in (guard / "guard.log").read_text()


@pytest.mark.parametrize("pgrep", [0, 2])
def test_release_process_or_failed_process_check_blocks_artifact_prune(
    guard: Path, pgrep: int
) -> None:
    assert _run(guard, pgrep=pgrep).returncode == 0
    assert not _calls(guard, "ac-release")


def test_release_cut_blocks_artifact_prune(guard: Path) -> None:
    (guard / "cut").touch()
    assert _run(guard).returncode == 0
    assert not _calls(guard, "ac-release")
    assert not _calls(guard, "pgrep")


def test_only_old_named_caches_and_allowed_tmp_files_are_selected(guard: Path) -> None:
    caches = {
        _directory(guard, "src/app/.next/cache"),
        _directory(guard, "src/app/node_modules/.cache"),
    }
    _directory(guard, "src/fresh/.next/cache", hours=1)
    _directory(guard, "src/app/.next/server")
    _directory(guard, "src/datasets/.next/cache")
    _directory(guard, "src/pre-promote-1/.next/cache")
    tmp_files = {_file(guard, "tmp/wb-ci123"), _file(guard, "tmp/a.tgz")}
    _file(guard, "tmp/recent.log", hours=1)
    _file(guard, "tmp/keep.txt")
    _file(guard, "tmp/nested/ignored.log")
    _directory(guard, "tmp/wb-ci-dir")
    outside = _directory(guard, "outside/.next/cache")
    (guard / "src" / "linked").symlink_to(outside.parent.parent, target_is_directory=True)
    # Removing a symlink to a cache is also outside the allowlist.
    (guard / "src/app/node_modules/link").symlink_to(outside, target_is_directory=True)
    result = _run(guard)
    assert result.returncode == 0, result.stderr
    assert _removed(guard) == caches | tmp_files
    assert all(p.exists() for p in _removed(guard)), "fake rm never deletes"
    log = (guard / "guard.log").read_text()
    assert "size_bytes=4096" in log
    assert "DO NOT LOG THESE CONTENTS" not in log


def test_tmp_owner_filter_excludes_other_users(guard: Path) -> None:
    _file(guard, "tmp/old.log")
    # Fake only the UID lookup; files belong to the test runner, not this UID.
    lookup = guard / "bin" / "id"
    lookup.write_text("#!/bin/bash\necho 2147483646\n")
    lookup.chmod(0o755)
    old_path = os.environ.get("PATH", "")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PATH", f"{guard / 'bin'}:{old_path}")
        assert _run(guard).returncode == 0
    assert not _removed(guard)


def test_backup_rotation_is_disabled_unless_exactly_one(guard: Path) -> None:
    _file(guard, "paperclip/paperclip-old.sql.gz")
    _file(guard, "backups/application/staging/old.dump")
    _file(guard, "backups/application/production/logical/old.dump")
    _directory(guard, "backups/staging-snapshots/old")
    assert _run(guard).returncode == 0
    assert not _removed(guard)


def test_approved_backup_retention_and_protected_paths(guard: Path) -> None:
    expected = set()
    for i in range(6):
        paperclip = _file(guard, f"paperclip/paperclip-{i}.sql.gz", hours=i + 1)
        dump = _file(guard, f"backups/application/staging/{i}.dump", hours=i + 1)
        snap = _directory(guard, f"backups/staging-snapshots/{i}", hours=i + 1)
        if i >= 4:
            expected |= {paperclip, snap}
        if i >= 3:
            expected.add(dump)
    expected.add(_file(guard, "backups/application/production/logical/old.sql.gz", hours=25))
    _file(guard, "backups/application/production/logical/new.dump", hours=23)
    for name in ["held", "production-snapshots", "restic", "offsite", "volumes", "media-safety"]:
        _file(guard, f"backups/{name}/old.dump")
    _file(guard, "paperclip/unrelated.sql.gz")
    _file(guard, "backups/application/staging/README")
    _file(guard, "backups/application/staging/pre-promote-old.dump")
    _file(guard, "backups/application/staging/logical/nested.dump")
    _file(guard, "backups/application/production/logical/pre-promote-old.dump")
    _directory(guard, "backups/staging-snapshots/pre-promote-old")
    _directory(guard, "backups/staging-snapshots/ancient/held")
    # Ensure the protected snapshot does not consume one of the retained slots.
    when = time.time() - 200 * 3600
    os.utime(guard / "backups/staging-snapshots/ancient", (when, when))
    result = _run(guard, config="BACKUP_ROTATION_APPROVED=1\n")
    assert result.returncode == 0, result.stderr
    assert _removed(guard) == expected


def test_retention_overrides_and_age_override(guard: Path) -> None:
    old = _file(guard, "paperclip/paperclip-old.sql.gz", hours=2)
    _file(guard, "paperclip/paperclip-new.sql.gz", hours=1)
    dump = _file(guard, "backups/application/staging/old.dump", hours=2)
    _file(guard, "backups/application/staging/new.dump", hours=1)
    logical = _file(guard, "backups/application/production/logical/old.dump", hours=3)
    snapshot = _directory(guard, "backups/staging-snapshots/old", hours=2)
    _directory(guard, "backups/staging-snapshots/new", hours=1)
    config = (
        "BACKUP_ROTATION_APPROVED=1\nKEEP_PAPERCLIP_BACKUPS=1\nKEEP_STAGING_DUMPS=1\n"
        "KEEP_SNAPSHOTS=1\nKEEP_PROD_LOGICAL_HOURS=2\nKEEP_RELEASES=5\n"
    )
    assert _run(guard, config=config).returncode == 0
    assert _removed(guard) == {old, dump, logical, snapshot}
    assert "5" in _calls(guard, "ac-release")[0]


def test_stop_inside_file_step_as_soon_as_target_met(guard: Path) -> None:
    _directory(guard, "src/a/.next/cache")
    _directory(guard, "src/b/.next/cache")
    # Initial measurement + five command steps, then the first cache removal.
    assert _run(guard, free="7,7,7,7,7,7,90").returncode == 0
    assert len(_removed(guard)) == 1
    assert not (guard / "metrics").exists()


def test_failed_removal_is_logged_and_other_candidates_continue(guard: Path) -> None:
    _directory(guard, "src/a/.next/cache")
    _directory(guard, "src/b/.next/cache")
    assert _run(guard, fail="rm").returncode == 0
    assert len(_removed(guard)) == 2
    assert "remove failed name=" in (guard / "guard.log").read_text()
    assert (guard / "metrics" / "disk-alert.json").exists()


@pytest.mark.parametrize("free", ["garbage", ""])
def test_bad_df_stops_before_cleanup(guard: Path, free: str) -> None:
    assert _run(guard, free=free).returncode == 1
    assert [c[0] for c in _calls(guard)] == ["df"]


@pytest.mark.parametrize("setting", ["KEEP_SNAPSHOTS=0", "TARGET_FREE_GB=oops", "KEEP_RELEASES=-1"])
def test_invalid_configuration_fails_before_cleanup(guard: Path, setting: str) -> None:
    assert _run(guard, config=setting + "\n").returncode == 1
    assert not _calls(guard)


@pytest.mark.parametrize("free", ["20", "30"])
def test_alert_only_below_critical_threshold(guard: Path, free: str) -> None:
    assert _run(guard, free=free).returncode == 0
    assert not (guard / "metrics").exists()


def test_critical_threshold_is_configurable(guard: Path) -> None:
    assert _run(guard, free="25", config="CRITICAL_FREE_GB=30\n").returncode == 0
    assert (guard / "metrics" / "disk-alert.json").exists()


def test_overlapping_guard_run_does_not_cleanup(guard: Path) -> None:
    with (guard / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert _run(guard).returncode == 0
    assert not _calls(guard)


def test_symlinked_cleanup_root_is_skipped(guard: Path) -> None:
    outside = _directory(guard, "outside/app/.next/cache")
    (guard / "src").rmdir()
    (guard / "src").symlink_to(outside.parents[2], target_is_directory=True)
    assert _run(guard).returncode == 0
    assert not _removed(guard)


def test_units_and_safe_defaults() -> None:
    service = SERVICE.read_text()
    timer = TIMER.read_text()
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/local/sbin/ac-disk-guard" in service
    assert "OnBootSec=3min" in timer
    assert "OnCalendar=*:0/10" in timer
    assert "WantedBy=timers.target" in timer
    assert "BACKUP_ROTATION_APPROVED=0" in CONF.read_text()
    assert "set -euo pipefail" in SCRIPT.read_text()


@pytest.mark.parametrize(
    "process",
    [
        "/bin/bash /usr/local/sbin/ac-ship --version v1.2.3",
        "/usr/bin/python3 /opt/ac-release/current/ac_release.py tick",
        "/usr/local/sbin/ac-release promote production",
    ],
)
def test_release_guard_matches_installed_entry_points(guard: Path, process: str) -> None:
    assert _run(guard, process=process).returncode == 0
    assert not _calls(guard, "ac-release")


@pytest.mark.parametrize("command", ["journalctl", "apt-get", "ac-release"])
def test_command_failures_do_not_prevent_later_cleanup(guard: Path, command: str) -> None:
    cache = _directory(guard, "src/app/.next/cache")
    assert _run(guard, fail=command).returncode == 0
    assert cache in _removed(guard)
    assert "status=1" in (guard / "guard.log").read_text()


def test_logical_captures_keep_metadata_and_dump_together(guard: Path) -> None:
    logical = "backups/application/production/logical"
    old = f"{logical}/20261026T120000.000000Z-100-production"
    new = f"{logical}/20261028T120000.000000Z-200-production"
    for name in [old, new]:
        _file(guard, f"{name}/backup.dump", hours=1)
        _file(guard, f"{name}/metadata.json", hours=1)
    when = time.time() - 30 * 3600
    os.utime(guard / old, (when, when))
    _directory(guard, f"{logical}/.production-active.capture.tmp")
    _file(guard, f"{logical}/backup.lock")
    assert _run(guard, config="BACKUP_ROTATION_APPROVED=1\n").returncode == 0
    assert _removed(guard) == {guard / old}


def test_unusual_filenames_are_logged_as_names_not_contents(guard: Path) -> None:
    path = _file(guard, "tmp/wb-ci space\nnewline.log")
    assert _run(guard).returncode == 0
    assert _removed(guard) == {path}
    log = (guard / "guard.log").read_text()
    assert "DO NOT LOG THESE CONTENTS" not in log
    assert "newline.log" in log


def test_repeated_runs_keep_the_same_retention_plan(guard: Path) -> None:
    old = _file(guard, "paperclip/paperclip-old.sql.gz", hours=2)
    _file(guard, "paperclip/paperclip-new.sql.gz", hours=1)
    config = "BACKUP_ROTATION_APPROVED=1\nKEEP_PAPERCLIP_BACKUPS=1\n"
    for _ in range(2):
        assert _run(guard, config=config).returncode == 0
        assert _removed(guard) == {old}
        assert json.loads((guard / "metrics" / "disk-alert.json").read_text())["free_gb"] == 7


def test_inherited_environment_cannot_approve_backup_rotation(
    guard: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(6):
        _file(guard, f"paperclip/paperclip-{i}.sql.gz", hours=i + 1)
    monkeypatch.setenv("BACKUP_ROTATION_APPROVED", "1")
    assert _run(guard).returncode == 0
    assert not _removed(guard)
    assert "backup rotation skipped" in (guard / "guard.log").read_text()


def _archive_candidates(guard: Path) -> set[Path]:
    old = {
        _file(guard, "paperclip/paperclip-old.sql.gz", hours=2),
        _file(guard, "backups/application/staging/old dump.sql.gz", hours=2),
        _directory(guard, "backups/staging-snapshots/old snapshot", hours=2),
    }
    _file(guard, "paperclip/paperclip-new.sql.gz", hours=1)
    _file(guard, "backups/application/staging/new.dump", hours=1)
    _directory(guard, "backups/staging-snapshots/new", hours=1)
    return old


ARCHIVE_CONFIG = (
    "BACKUP_ROTATION_APPROVED=1\nARCHIVE_ENABLED=1\nKEEP_PAPERCLIP_BACKUPS=1\n"
    "KEEP_STAGING_DUMPS=1\nKEEP_SNAPSHOTS=1\n"
)


@pytest.mark.parametrize("fail", ["", "ac-archive-put"])
def test_archive_before_removal_or_keep_and_continue_on_failure(guard: Path, fail: str) -> None:
    old = _archive_candidates(guard)
    production = _file(guard, "backups/application/production/logical/ancient.dump", hours=1000)
    _file(guard, "backups/production-snapshots/ancient/backup.dump", hours=1000)
    _file(guard, "backups/staging-snapshots/protected/held/backup.dump", hours=1000)
    when = time.time() - 1000 * 3600
    os.utime(guard / "backups/staging-snapshots/protected", (when, when))
    assert _run(guard, config=ARCHIVE_CONFIG, fail=fail).returncode == 0
    archives = _calls(guard, "ac-archive-put")
    assert {Path(c[1]) for c in archives} == old
    assert {c[2] for c in archives} == {
        "backups/paperclip/paperclip-old.sql.gz",
        "backups/staging/old dump.sql.gz",
        "backups/snapshots/old snapshot",
    }
    assert production not in _removed(guard)
    assert production.exists()
    assert _removed(guard) == (set() if fail else old)
    calls = _calls(guard)
    for call in archives:
        removes = [c for c in calls if c[0] == "rm" and c[-1] == call[1]]
        assert not removes if fail else calls.index(call) < calls.index(removes[0])
    log = (guard / "guard.log").read_text()
    assert "untrusted provider output" not in log
    assert "archive failed; kept" in log if fail else "archived key=" in log


def test_archive_disabled_retains_existing_approved_rotation(guard: Path) -> None:
    old = _archive_candidates(guard)
    production = _file(guard, "backups/application/production/logical/old.dump", hours=25)
    assert (
        _run(
            guard, config=ARCHIVE_CONFIG.replace("ARCHIVE_ENABLED=1", "ARCHIVE_ENABLED=0")
        ).returncode
        == 0
    )
    assert not _calls(guard, "ac-archive-put")
    assert _removed(guard) == old | {production}


def test_archive_needs_config_opt_in_and_backup_rotation_approval(
    guard: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _archive_candidates(guard)
    monkeypatch.setenv("ARCHIVE_ENABLED", "1")
    assert _run(guard, config=ARCHIVE_CONFIG.replace("ARCHIVE_ENABLED=1\n", "")).returncode == 0
    assert not _calls(guard, "ac-archive-put")
    assert _removed(guard) == old
    (guard / "calls").unlink()
    assert _run(guard, config="ARCHIVE_ENABLED=1\n").returncode == 0
    assert not _calls(guard, "ac-archive-put")
    assert not _removed(guard)


def test_invalid_archive_configuration_fails_before_cleanup(guard: Path) -> None:
    assert _run(guard, config="ARCHIVE_ENABLED=yes\n").returncode == 1
    assert not _calls(guard)


def test_archive_default_is_disabled() -> None:
    assert "ARCHIVE_ENABLED=0" in CONF.read_text()


def test_raw_spool_is_inventoried_even_with_sufficient_disk_and_never_pruned(guard, monkeypatch):
    spool = guard / "raw" / "production"
    spool.mkdir(parents=True)
    raw = spool / "hour.ndjson"
    raw.write_bytes(b"durable")
    monkeypatch.setenv("AC_DISK_TELEMETRY", str(spool.parent))
    result = _run(guard, free="100")
    assert result.returncode == 0
    assert "telemetry_spool=" in (guard / "guard.log").read_text()
    assert '"bytes": 7' in (guard / "guard.log").read_text()
    assert raw.read_bytes() == b"durable"

"""C0: unchanged Root import, fictional studio locks and offline SHA installer."""

from __future__ import annotations

import builtins
import fcntl
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "infra/watchdog/ac_watchdog.py"
INSTALLER_PATH = "infra/watchdog/install-watchdog.sh"
FIXTURE = json.loads((ROOT / "tests/infra/fixtures/ac_watchdog/c0.json").read_text())
STUDIO = FIXTURE["studio"]
GIT = shutil.which("git")
BASH = shutil.which("bash")
assert GIT is not None and BASH is not None


@pytest.fixture
def watchdog(monkeypatch):
    """Import actual source with no runtime files, network, DB or Telegram clients."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Live watchdog client called")

    telegram = ModuleType("ac_telegram")
    monkeypatch.setattr(
        telegram, "LINK", "https://fictional.example.invalid/issues/{}", raising=False
    )
    for name in ("paperclip", "send", "remember_message"):
        monkeypatch.setattr(telegram, name, forbidden, raising=False)
    postgres = ModuleType("psycopg")
    monkeypatch.setattr(postgres, "connect", forbidden, raising=False)
    monkeypatch.setitem(sys.modules, "ac_telegram", telegram)
    monkeypatch.setitem(sys.modules, "psycopg", postgres)
    monkeypatch.setattr(sys, "argv", ["ac_watchdog.py", "--dry-run"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(subprocess, "run", forbidden)
    spec = importlib.util.spec_from_file_location("c0_watchdog", ROOT / SOURCE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module.ACT
    yield module


def test_import_is_byte_identical_to_root_export():
    source = (ROOT / SOURCE_PATH).read_bytes()
    metadata = FIXTURE["source"]
    assert hashlib.sha256(source).hexdigest() == metadata["sanitized_sha256"]
    assert metadata["original_sha256"] == metadata["sanitized_sha256"]
    assert len(source.splitlines()) == metadata["lines"]
    assert metadata["redactions"] == metadata["config_injection"] == []
    assert STUDIO["old_lock"].encode() not in source
    assert b"/run/user/1002" not in source


@pytest.fixture
def studio_runtime(watchdog, tmp_path, monkeypatch):
    home = tmp_path / "fictional-home"
    state = home / ".local/state/ac-studio-sync/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps(STUDIO["initial_state"]))
    lock_path = tmp_path / "shared-studio.lock"
    lock_path.touch()
    calls = []
    opened = []
    sleeps = []
    release_on_sleep = []
    original_open = builtins.open

    def mapped_open(file, *args, **kwargs):
        # Only the literal lock path is redirected; FREEZE itself is unchanged.
        if str(file).startswith("/run/"):
            opened.append(str(file))
            assert str(file) == STUDIO["lock"]
            file = lock_path
        return original_open(file, *args, **kwargs)

    def sleep(seconds):
        sleeps.append(seconds)
        if release_on_sleep:
            fcntl.flock(release_on_sleep.pop(), fcntl.LOCK_UN)

    def as_acdev(command, timeout):
        argv = shlex.split(command)
        calls.append((argv, timeout))
        assert argv == ["python3", "-c", watchdog.FREEZE, str(STUDIO["number"]), STUDIO["sha"]]
        assert timeout == 120
        with monkeypatch.context() as patch:
            patch.setattr(Path, "home", classmethod(lambda cls: home))
            patch.setattr(builtins, "open", mapped_open)
            patch.setattr(time, "sleep", sleep)
            patch.setattr(sys, "argv", ["-c", *argv[3:]])
            try:
                exec(compile(watchdog.FREEZE, "<unchanged-freeze>", "exec"), {})  # noqa: S102
            except SystemExit as exit_status:
                return SimpleNamespace(returncode=exit_status.code)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(watchdog, "as_acdev", as_acdev)
    return SimpleNamespace(
        home=home,
        state=state,
        lock=lock_path,
        calls=calls,
        opened=opened,
        sleeps=sleeps,
        release_on_sleep=release_on_sleep,
    )


def test_freeze_records_exact_head_using_current_lock(watchdog, studio_runtime):
    assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    expected = json.loads(json.dumps(STUDIO["initial_state"]))
    expected["approvals"][str(STUDIO["number"])] = STUDIO["sha"]
    assert json.loads(studio_runtime.state.read_text()) == expected
    assert studio_runtime.opened == [STUDIO["lock"]]
    assert studio_runtime.sleeps == []
    assert list(studio_runtime.state.parent.iterdir()) == [studio_runtime.state]


def test_held_shared_lock_refuses_freeze_without_overwriting_state(watchdog, studio_runtime):
    before = studio_runtime.state.read_bytes()
    with studio_runtime.lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert not watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.state.read_bytes() == before
    assert studio_runtime.opened == [STUDIO["lock"]]
    assert studio_runtime.sleeps == [1] * 90
    assert list(studio_runtime.state.parent.iterdir()) == [studio_runtime.state]


def test_freeze_waits_for_shared_lock_release(watchdog, studio_runtime):
    with studio_runtime.lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        studio_runtime.release_on_sleep.append(holder)
        assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.sleeps == [1]
    assert (
        json.loads(studio_runtime.state.read_text())["approvals"][str(STUDIO["number"])]
        == (STUDIO["sha"])
    )


def test_old_user_lock_does_not_block_current_freeze(watchdog, studio_runtime, tmp_path):
    # The old path is fictional too; holding it must have no effect on FREEZE.
    with (tmp_path / "old-user-1002.lock").open("a") as old_holder:
        fcntl.flock(old_holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.opened == [STUDIO["lock"]]
    assert studio_runtime.sleeps == []


def test_absent_studio_state_is_existing_noop(watchdog, studio_runtime):
    studio_runtime.state.unlink()
    studio_runtime.state.parent.rmdir()
    assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.opened == []
    assert not studio_runtime.state.parent.exists()


@pytest.mark.parametrize(
    ("freeze_ok", "held", "main", "checks", "expected_freezes", "expected_merges"),
    [
        (False, False, "green", "success", 1, 0),
        (True, False, "green", "success", 1, 1),
        (True, True, "green", "success", 0, 0),
        (True, False, "red", "success", 0, 0),
        (True, False, None, "success", 0, 0),
        (True, False, "green", "failure", 0, 0),
    ],
)
def test_studio_merge_preserves_freeze_hold_main_and_check_guards(
    watchdog, monkeypatch, freeze_ok, held, main, checks, expected_freezes, expected_merges
):
    number, sha = STUDIO["number"], STUDIO["sha"]
    branch = watchdog.STUDIO_BRANCH + "fictional"
    freezes, merges, notes = [], [], []

    def github(path):
        if path == "/pulls?state=open&per_page=20":
            return [{"number": number, "head": {"sha": sha, "ref": branch}}]
        assert path == f"/commits/{sha}/check-runs?per_page=100"
        return {"check_runs": [{"status": "completed", "conclusion": checks}]}

    def freeze(*args):
        freezes.append(args)
        return freeze_ok

    def merge(*args):
        merges.append(args)
        return True, ""

    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: ("AUT-FAKE",)))
    monkeypatch.setattr(watchdog, "ACT", True)
    monkeypatch.setattr(watchdog, "gh_api", github)
    monkeypatch.setattr(
        watchdog, "pr_approvals", lambda *args: ("fake-task", "fake-cto", "fake-ceo", None, None)
    )
    monkeypatch.setattr(watchdog, "merge_held", lambda *args: held)
    monkeypatch.setattr(watchdog, "freeze_studio_head", freeze)
    monkeypatch.setattr(watchdog, "merge", merge)
    monkeypatch.setattr(watchdog.tg, "paperclip", lambda *args: notes.append(args))
    watchdog.pull_requests(conn, {"sent": {}}, {}, [], main=main)
    assert freezes == [(number, sha)] * expected_freezes
    assert merges == [(number, sha, branch)] * expected_merges
    assert len(notes) == expected_merges


def git(repo, *args):
    result = subprocess.run(  # noqa: S603 - private fictional repository, fixed git argv
        [GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def installer_repo(tmp_path):
    repo = tmp_path / "fictional-repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fictional C0 operator")
    git(repo, "config", "user.email", "fictional@example.invalid")
    for path in (SOURCE_PATH, INSTALLER_PATH):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
        target.chmod(0o755)
    git(repo, "add", "infra/watchdog")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional merged source")
    revision = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", revision)
    return repo, revision


def install(repo, *args):
    return subprocess.run(  # noqa: S603 - checked-in installer, private fictional repo
        [BASH, str(repo / INSTALLER_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"], "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def snapshot(repo):
    return {
        str(path.relative_to(repo)): (
            path.read_bytes(),
            path.stat().st_mode,
            path.stat().st_mtime_ns,
        )
        for path in repo.rglob("*")
        if path.is_file()
    }


def assert_refused(result):
    assert result.returncode == 2
    assert result.stderr.strip() == "Refused: unverified watchdog source"
    assert "Verified source" not in result.stdout


def test_verified_installer_dry_run_writes_nothing_and_is_repeatable(installer_repo, tmp_path):
    repo, revision = installer_repo
    # Trap any host-write command; git and sha256sum are the real read-only tools.
    tools = tmp_path / "tools"
    tools.mkdir()
    marker = tmp_path / "host-write-attempt"
    for name in ("sudo", "mktemp", "cp", "mv", "chmod", "chown", "install", "systemctl", "rm"):
        trap = tools / name
        trap.write_text(f"#!/bin/sh\nprintf attempted > {shlex.quote(str(marker))}\nexit 99\n")
        trap.chmod(0o755)
    before = snapshot(repo)
    for args in (("--dry-run",), ()):
        result = subprocess.run(  # noqa: S603 - private repo and host-write traps
            [BASH, str(repo / INSTALLER_PATH), *args, "--source-revision", revision],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": f"{tools}:{os.environ['PATH']}", "LC_ALL": "C"},
        )
        assert result.returncode == 0, result.stderr
        assert revision in result.stdout
        assert FIXTURE["source"]["sanitized_sha256"] in result.stdout
        assert "no host files changed" in result.stdout
        assert snapshot(repo) == before
        assert not marker.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--dry-run"],
        ["--dry-run", "--source-revision"],
        ["--dry-run", "--source-revision", "main"],
        ["--dry-run", "--source-revision", "a" * 7],
        ["--dry-run", "--source-revision", "A" * 40],
        ["--dry-run", "--source-revision", "0" * 40],
        ["--install", "--source-revision", "invalid"],
    ],
)
def test_installer_refuses_missing_invalid_or_unknown_revision(installer_repo, args):
    repo, _ = installer_repo
    before = snapshot(repo)
    assert_refused(install(repo, *args))
    assert snapshot(repo) == before


@pytest.mark.parametrize("path", [SOURCE_PATH, INSTALLER_PATH])
def test_installer_refuses_digest_mismatch_before_any_install(installer_repo, path):
    repo, revision = installer_repo
    with (repo / path).open("a") as altered:
        altered.write("\n# fictional unreviewed change\n")
    before = snapshot(repo)
    assert_refused(install(repo, "--install", "--source-revision", revision))
    assert snapshot(repo) == before


def test_installer_refuses_revision_not_on_main(installer_repo):
    repo, _ = installer_repo
    with (repo / SOURCE_PATH).open("a") as altered:
        altered.write("\n# fictional unmerged change\n")
    git(repo, "add", SOURCE_PATH)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional unmerged source")
    revision = git(repo, "rev-parse", "HEAD")
    assert_refused(install(repo, "--dry-run", "--source-revision", revision))


def test_installer_refuses_noncommit_revision(installer_repo):
    repo, _ = installer_repo
    blob = git(repo, "rev-parse", f"HEAD:{SOURCE_PATH}")
    assert_refused(install(repo, "--dry-run", "--source-revision", blob))


def test_installer_refuses_missing_main_evidence(installer_repo):
    repo, revision = installer_repo
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert_refused(install(repo, "--dry-run", "--source-revision", revision))


@pytest.mark.parametrize("symlink", [False, True])
def test_installer_refuses_missing_or_symlink_source(installer_repo, tmp_path, symlink):
    repo, revision = installer_repo
    source = repo / SOURCE_PATH
    source.unlink()
    if symlink:
        copy = tmp_path / "untracked-source.py"
        shutil.copyfile(ROOT / SOURCE_PATH, copy)
        source.symlink_to(copy)
    assert_refused(install(repo, "--dry-run", "--source-revision", revision))


def test_installer_refuses_duplicate_or_conflicting_options(installer_repo):
    repo, revision = installer_repo
    for args in (
        ["--dry-run", "--install", "--source-revision", revision],
        ["--source-revision", revision, "--source-revision", revision],
        ["--unknown", "--source-revision", revision],
    ):
        assert_refused(install(repo, *args))

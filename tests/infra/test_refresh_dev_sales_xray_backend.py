"""Isolated refresh contract tests; fake host commands and never start services."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/refresh-dev-sales-xray-backend.py"
spec = importlib.util.spec_from_file_location("dev_refresh", SCRIPT)
refresh = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = refresh
assert spec.loader
spec.loader.exec_module(refresh)
native_spec = importlib.util.spec_from_file_location(
    "native_inputs", ROOT / "infra/application/scripts/native_artifact_compatibility.py"
)
native = importlib.util.module_from_spec(native_spec)
sys.modules[native_spec.name] = native
assert native_spec.loader
native_spec.loader.exec_module(native)


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - test invokes fixed Git plumbing commands
        ["git", *args],  # noqa: S607 - system Git is the test fixture's fixed executable
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class FakeCommands:
    def __init__(self, web_sha: str):
        self.web_sha = web_sha
        self.branch_name = "task/ui/example"
        self.calls: list[tuple[list[str], dict]] = []
        self.fail_api_restart = False
        self.failed_once = False
        self.studio_conflict = False
        self.smoke_failure = False

    def __call__(self, argv, **kwargs):
        args = list(map(str, argv))
        self.calls.append((args, kwargs))
        if self.smoke_failure and any(item.endswith("/ac_smoke.py") for item in args):
            return subprocess.CompletedProcess(args, 1, b"", b"secret smoke output")
        if args[:2] == ["git", "--no-replace-objects"]:
            result = subprocess.run(  # noqa: S603 - args are fixed Git commands for a temp mirror
                args, capture_output=True, check=False, timeout=30
            )
            if len(args) > 3 and args[3] == "show":
                assert result.returncode == 0, result.stderr.decode()
            return result
        if args[:2] == ["git", "clone"] or args[:2] == ["git", "-C"]:
            return subprocess.run(  # noqa: S603 - args are fixed Git commands for a temp checkout
                args, capture_output=True, check=False, timeout=30
            )
        if args[0] == "ac-release":
            return subprocess.CompletedProcess(args, 0, b"{}", b"")
        if args[0] == "uv":
            assert args == ["uv", "sync", "--frozen", "--no-dev", "--no-build"]
        elif args[0] == "setpriv":
            assert args[1:4] == ["--reuid=10001", "--regid=10001", "--clear-groups"]
            assert kwargs["env"]["AC_ENVIRONMENT"] == "development"
        elif args[0] == "systemctl":
            if (
                self.fail_api_restart
                and not self.failed_once
                and args == ["systemctl", "restart", "ac-dev-api.service"]
            ):
                self.failed_once = True
                return subprocess.CompletedProcess(args, 1, b"", b"secret diagnostic")
        elif args[0] == "curl":
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"release_id": self.web_sha}).encode(), b""
            )
        elif args[0] == "runuser":
            tail = args[4:]
            if tail[:2] == ["git", "rev-parse"] and "--abbrev-ref" in tail:
                return subprocess.CompletedProcess(args, 0, (self.branch_name + "\n").encode(), b"")
            if tail[:2] == ["git", "rev-parse"] and tail[-1] == "HEAD":
                return subprocess.CompletedProcess(args, 0, (self.web_sha + "\n").encode(), b"")
            if tail[:2] == ["git", "merge"] and self.studio_conflict:
                return subprocess.CompletedProcess(args, 1, b"", b"conflict details")
            if tail[:2] == ["git", "rev-parse"] and "MERGE_HEAD" in tail:
                return subprocess.CompletedProcess(args, 0, b"merge\n", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    app = tmp_path / "application"
    releases = app / "releases"
    releases.mkdir(parents=True)
    mirror = tmp_path / "mirror.git"
    git("init", "--bare", str(mirror))
    work = tmp_path / "work"
    git("clone", str(mirror), str(work))
    git("config", "user.email", "test@example.invalid", cwd=work)
    git("config", "user.name", "Test", cwd=work)
    for name in native.INPUT_FILES:
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name == "infra/application/scripts/native_artifact_compatibility.py":
            shutil.copyfile(ROOT / name, path)
        else:
            path.write_text("same native input\n")
    helper = work / "infra/application/scripts/native_artifact_compatibility.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "infra/application/scripts/native_artifact_compatibility.py", helper)
    (work / "scripts/ops").mkdir(parents=True)
    (work / "scripts/ops/ac_smoke.py").write_text("# fake smoke\n")
    git("add", ".", cwd=work)
    git("commit", "-m", "first", cwd=work)
    source = git("rev-parse", "HEAD", cwd=work)
    git("push", "origin", "HEAD", cwd=work)

    def release(sha):
        target = releases / sha
        target.mkdir(parents=True, exist_ok=True)
        helper = target / "infra/application/scripts/native_artifact_compatibility.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "infra/application/scripts/native_artifact_compatibility.py", helper)
        return target

    release(source)
    (app / "current-staging").symlink_to(releases / source)
    dev = tmp_path / "etc/authority-closers/development"
    dev.mkdir(parents=True)
    (dev / "api.env").write_text(
        "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL=postgresql://user:secret@dev/db\n"
    )
    (dev / "service.operator-template.json").write_text(
        json.dumps({"environment": "development", "release_id": "old"})
    )
    native_units = app / "operator-inputs/development/native-units.json"
    native_units.parent.mkdir(parents=True)
    native_units.write_text(json.dumps({"environment": "development", "helper_source_sha": source}))
    ui = tmp_path / "ui"
    ui.mkdir()
    paths = refresh.Paths(
        application=app,
        backend=tmp_path / "development/backend",
        mirror=mirror,
        store=tmp_path / "release-store",
        development=dev,
        native_units=native_units,
        worker_template=dev / "service.operator-template.json",
        api_dropin=tmp_path / "systemd/ac-dev-api.service.d/release.conf",
        worker_dropin=tmp_path / "systemd/ac-dev-sales-xray-worker.service.d/manifest.conf",
        studio=ui,
        studio_lock=tmp_path / "run/ac-studio-sync/ac-studio-sync.lock",
        owner_uid=os.geteuid(),
    )
    monkeypatch.setattr(refresh.shutil, "which", lambda _: "/usr/local/bin/ac-studio-sync")
    return paths, source, work, release


def test_first_run_and_same_sha_noop(tree, capsys):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    value = refresh.refresh(paths, fake, uid=0)
    assert value["target"] == sha and value["migrated"] == "yes"
    assert (paths.backend / ".ac-release-id").read_text().strip() == sha
    assert "AC_RELEASE_ID=" + sha in paths.api_dropin.read_text()
    assert "AC_DEV_WORKER_MANIFEST_SHA256=" in paths.worker_dropin.read_text()
    assert json.loads((paths.development / "service.json").read_text())["release_id"] == sha
    assert any(args[0] == "uv" for args, _ in fake.calls)
    assert any(args[0] == "setpriv" for args, _ in fake.calls)
    assert any(args[:2] == ["git", "clone"] for args, _ in fake.calls)
    assert any(args[:4] == ["runuser", "-u", "acdev", "--"] for args, _ in fake.calls)
    migration = next(args for args, _ in fake.calls if args[0] == "setpriv")
    assert migration[-3:] == [str(paths.backend / ".venv/bin/alembic"), "upgrade", "head"]
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    assert json.loads(output)["health"]["ok"]
    assert "secret" not in output and "postgresql://" not in output
    calls = len(fake.calls)
    noop = refresh.refresh(paths, fake, uid=0)
    assert noop["noop"]
    assert not any(args[0] in ("uv", "setpriv", "systemctl") for args, _ in fake.calls[calls:])


def test_staging_pick_uses_mirror_commit_and_stored_core(tree):
    paths, source, work, release = tree
    (work / "ordinary.txt").write_text("pick commit\n")
    git("add", ".", cwd=work)
    git("commit", "-m", "pick", cwd=work)
    picked = git("rev-parse", "HEAD", cwd=work)
    git("push", "origin", "HEAD", cwd=work)
    release(picked)
    provenance = paths.store / picked / "core.provenance.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text(
        json.dumps(
            {"run_id": 1, "artifact_id": 2, "artifact_name": "core", "artifact_digest": "sha256:x"}
        )
    )

    def status_runner(argv, **kwargs):
        if argv[0] == "ac-release":
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"staging_pick": {"core": picked}}).encode(), b""
            )
        return FakeCommands(source)(argv, **kwargs)

    assert refresh.select_target(paths, status_runner) == picked


def test_native_input_change_refuses_before_checkout(tree):
    paths, source, work, release = tree
    changed = native.INPUT_FILES[0]
    (work / changed).write_text("changed native input\n")
    git("add", changed, cwd=work)
    git("commit", "-m", "native change", cwd=work)
    target = git("rev-parse", "HEAD", cwd=work)
    git("push", "origin", "HEAD", cwd=work)
    release(target)
    (paths.application / "current-staging").unlink()
    (paths.application / "current-staging").symlink_to(paths.application / "releases" / target)
    with pytest.raises(refresh.RefreshError, match="dev_native_inputs_changed"):
        refresh.refresh(paths, FakeCommands(target), uid=0)
    assert not paths.backend.exists()


def test_non_development_environment_refuses(tree):
    paths, sha, _, _ = tree
    (paths.development / "api.env").write_text("AC_ENVIRONMENT=staging\n")
    with pytest.raises(refresh.RefreshError, match="development_environment_required"):
        refresh.refresh(paths, FakeCommands(sha), uid=0)
    assert not paths.backend.exists()


def test_non_root_refuses(tree):
    paths, sha, _, _ = tree
    with pytest.raises(refresh.RefreshError, match="root_required"):
        refresh.refresh(paths, FakeCommands(sha), uid=10001)
    assert not paths.backend.exists()


def test_restart_failure_restores_checkout_marker_and_dropins(tree, capsys):
    paths, old, work, release = tree
    fake = FakeCommands(old)
    refresh.refresh(paths, fake, uid=0)
    paths.api_dropin.write_text("old api dropin\n")
    paths.worker_dropin.write_text("old worker dropin\n")
    (paths.development / "service.json").write_text("old manifest\n")
    old_marker = (paths.backend / ".ac-release-id").read_bytes()
    old_api = paths.api_dropin.read_bytes()
    old_worker = paths.worker_dropin.read_bytes()
    old_manifest = (paths.development / "service.json").read_bytes()
    (work / "ordinary.txt").write_text("next core\n")
    git("add", ".", cwd=work)
    git("commit", "-m", "next", cwd=work)
    new = git("rev-parse", "HEAD", cwd=work)
    git("push", "origin", "HEAD", cwd=work)
    release(new)
    (paths.application / "current-staging").unlink()
    (paths.application / "current-staging").symlink_to(paths.application / "releases" / new)
    paths.native_units.write_text(
        json.dumps({"environment": "development", "helper_source_sha": new})
    )
    failed = FakeCommands(new)
    failed.fail_api_restart = True
    with pytest.raises(refresh.RefreshError):
        refresh.refresh(paths, failed, uid=0)
    assert git("-C", str(paths.backend), "rev-parse", "HEAD") == old
    assert (paths.backend / ".ac-release-id").read_bytes() == old_marker
    assert paths.api_dropin.read_bytes() == old_api
    assert paths.worker_dropin.read_bytes() == old_worker
    assert (paths.development / "service.json").read_bytes() == old_manifest
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err
    result = json.loads(captured.out.splitlines()[-1])
    assert result["error"] == "command_failed" and result["restarted"] == "rollback_attempted"


def test_main_branch_uses_ff_only_and_smoke_failure_keeps_backend(tree, capsys):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    fake.branch_name = "main"
    fake.smoke_failure = True
    with pytest.raises(refresh.RefreshError, match="dev_smoke_failed"):
        refresh.refresh(paths, fake, uid=0)
    merge = next(args for args, _ in fake.calls if "merge" in args)
    assert merge[-2:] == ["--ff-only", "origin/main"]
    assert git("-C", str(paths.backend), "rev-parse", "HEAD") == sha
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["smoke"] == "fail"
    assert not any(
        any(word in args for word in ("reset", "stash", "clean"))
        for args, _ in fake.calls
        if args[0] == "runuser"
    )


def test_studio_conflict_aborts_and_alerts_without_backend_rollback(tree, capsys):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    fake.studio_conflict = True
    with pytest.raises(refresh.RefreshError, match="studio_merge_failed"):
        refresh.refresh(paths, fake, uid=0)
    assert any(args[-2:] == ["merge", "--abort"] for args, _ in fake.calls)
    assert git("-C", str(paths.backend), "rev-parse", "HEAD") == sha
    captured = capsys.readouterr()
    assert '"kind": "alert"' in captured.err
    assert not any(
        any(word in args for word in ("reset", "stash", "clean"))
        for args, _ in fake.calls
        if args[0] == "runuser"
    )


def test_staging_pick_without_stored_build_falls_back(tree):
    paths, source, _, _ = tree
    pick = source

    def status_runner(argv, **kwargs):
        if argv[0] == "ac-release":
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"staging_pick": {"core": pick}}).encode(), b""
            )
        return FakeCommands(source)(argv, **kwargs)

    assert refresh.select_target(paths, status_runner) == source


def test_smoke_absent_is_skipped(tree):
    paths, sha, _, _ = tree
    paths.backend.mkdir(parents=True)
    assert refresh.smoke(paths, FakeCommands(sha), sha, sha) == "skipped"


def test_systemd_timer_and_service_contract():
    import configparser

    directory = ROOT / "infra/application/development"
    service = (directory / "ac-dev-sales-xray-refresh.service").read_text()
    timer = (directory / "ac-dev-sales-xray-refresh.timer").read_text()
    assert "User=root" in service and "MemoryMax=" in service and "CPUQuota=" in service
    assert "/current-staging/infra/application/scripts/refresh-dev-sales-xray-backend.py" in service
    assert "OnUnitActiveSec=10min" in timer
    assert "Unit=ac-dev-sales-xray-refresh.service" in timer
    parsed = configparser.ConfigParser(interpolation=None)
    parsed.read_string(service)
    parsed.read_string(timer)
    assert parsed["Timer"]["OnUnitActiveSec"] == "10min"
    systemd_analyze = shutil.which("systemd-analyze")
    if systemd_analyze:
        result = subprocess.run(  # noqa: S603 - fixed local parser command
            [
                systemd_analyze,
                "verify",
                str(directory / "ac-dev-sales-xray-refresh.service"),
                str(directory / "ac-dev-sales-xray-refresh.timer"),
            ],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()

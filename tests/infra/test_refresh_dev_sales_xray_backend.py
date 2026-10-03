"""Isolated refresh contract tests; fake host commands and never start services."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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


UNIT_ORDER = (
    "ac-dev-api.service",
    "ac-dev-sales-xray-worker.service",
    "ac-dev-outbox-worker.service",
)


def restarts(fake):
    return [args[2] for args, _ in fake.calls if args[:2] == ["systemctl", "restart"]]


class FakeCommands:
    def __init__(self, web_sha: str):
        self.web_sha = web_sha
        self.branch_name = "task/ui/example"
        self.calls: list[tuple[list[str], dict]] = []
        self.fail_api_restart = False
        self.failed_once = False
        self.studio_conflict = False
        self.smoke_failure = False
        self.health_failures = 0
        self.health_calls = 0
        self.units = dict.fromkeys(UNIT_ORDER, "inactive")
        self.fail = set()
        self.restart_status = 1

    def step(self, args):
        """Return the sandboxed argv after ``--`` for a systemd-run call."""
        return args[args.index("--") + 1 :]

    def __call__(self, argv, **kwargs):
        args = list(map(str, argv))
        self.calls.append((args, kwargs))
        if self.smoke_failure and any(item.endswith("/ac_smoke.py") for item in args):
            return subprocess.CompletedProcess(args, 1, b"", b"secret smoke output")
        if args[:2] == ["git", "clone"] and "clone" in self.fail:
            return subprocess.CompletedProcess(args, 128, b"", b"secret clone output")
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
            if "uv" in self.fail:
                return subprocess.CompletedProcess(args, 2, b"", b"secret uv output")
        elif args[0] == "systemd-run":
            assert args[1:5] == ["--wait", "--collect", "--quiet", "--service-type=exec"]
            assert "User=10001" in args and "Group=10001" in args
            if self.step(args)[-2:] == ["upgrade", "head"] and "migration" in self.fail:
                return subprocess.CompletedProcess(args, 1, b"", b"postgresql://secret")
        elif args[0] == "systemctl":
            if args[1] == "is-active":
                state = self.units[args[2]]
                return subprocess.CompletedProcess(
                    args, 0 if state == "active" else 3, (state + "\n").encode(), b""
                )
            if args[1] == "stop":
                if "stop" in self.fail:
                    return subprocess.CompletedProcess(args, 1, b"", b"secret stop")
                self.units[args[2]] = "inactive"
            if (
                self.fail_api_restart
                and not self.failed_once
                and args == ["systemctl", "restart", "ac-dev-api.service"]
            ):
                self.failed_once = True
                self.units[args[2]] = "failed"
                return subprocess.CompletedProcess(
                    args, self.restart_status, b"", b"secret diagnostic"
                )
            if args[1] == "restart":
                self.units[args[2]] = "active"
        elif args[0] == "curl":
            self.health_calls += 1
            if self.health_failures:
                self.health_failures -= 1
                return subprocess.CompletedProcess(args, 22, b"", b"not ready")
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"status": "ready", "release_id": self.web_sha}).encode(),
                b"",
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


def identity(monkeypatch, *, missing=False, groups=(10001,), name="ac-sales-xray-runtime"):
    def getpwuid(uid):
        if missing or uid != 10001:
            raise KeyError(uid)
        return SimpleNamespace(pw_name=name, pw_uid=10001, pw_gid=10001)

    monkeypatch.setattr(refresh.pwd, "getpwuid", getpwuid)
    monkeypatch.setattr(
        refresh.grp,
        "getgrgid",
        lambda gid: SimpleNamespace(gr_name="ac-sales-xray-native", gr_gid=gid, gr_mem=[]),
    )
    monkeypatch.setattr(refresh.os, "getgrouplist", lambda _user, _gid: list(groups))


def sandbox_steps(fake):
    return [args for args, _ in fake.calls if args[0] == "systemd-run"]


def systemctl(fake, start=0):
    return [args[1:] for args, _ in fake.calls[start:] if args[0] == "systemctl"]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        refresh.pwd,
        "getpwnam",
        lambda _: SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid()),
    )
    identity(monkeypatch)
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
        helper = target / "scripts/native_artifact_compatibility.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "infra/application/scripts/native_artifact_compatibility.py", helper)
        shutil.copyfile(SCRIPT, target / "scripts/refresh-dev-sales-xray-backend.py")
        return target

    release(source)
    (app / "current-staging").symlink_to(releases / source)
    dev = tmp_path / "etc/authority-closers/development"
    dev.mkdir(parents=True)
    (dev / "api.env").write_text(
        "AC_ENVIRONMENT=development\nAC_DATABASE_URL=postgresql://user:fake@dev/db\n"
    )
    migrator_env = dev / "migrator.env"
    migrator_env.write_text(
        "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL=postgresql://user:secret@dev/db\n"
    )
    migrator_env.chmod(0o600)
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
        migrator_env=migrator_env,
        native_units=native_units,
        worker_template=dev / "service.operator-template.json",
        api_dropin=tmp_path / "systemd/ac-dev-api.service.d/release.conf",
        worker_dropin=tmp_path / "systemd/ac-dev-sales-xray-worker.service.d/manifest.conf",
        studio=ui,
        studio_lock=tmp_path / "run/ac-studio-sync/ac-studio-sync.lock",
        owner_uid=os.geteuid(),
    )
    real_which = shutil.which

    def fake_which(name, path=None):
        if name == "uv":
            return "/usr/local/bin/uv"
        if name == "ac-studio-sync":
            return "/usr/local/bin/ac-studio-sync"
        if name == "systemd-run":
            return "/usr/bin/systemd-run"
        return real_which(name, path=path)

    monkeypatch.setattr(refresh.shutil, "which", fake_which)
    return paths, source, work, release


def test_first_run_and_same_sha_noop(tree, capsys, monkeypatch):
    paths, sha, _, _ = tree
    assert (
        paths.application / "current-staging/scripts/refresh-dev-sales-xray-backend.py"
    ).is_file()
    fake = FakeCommands(sha)
    fake.health_failures = 3
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)
    value = refresh.refresh(paths, fake, uid=0)
    assert value["target"] == sha and value["migrated"] == "yes"
    assert (paths.backend / ".ac-release-id").read_text().strip() == sha
    assert "AC_RELEASE_ID=" + sha in paths.api_dropin.read_text()
    assert "AC_DEV_WORKER_MANIFEST_SHA256=" in paths.worker_dropin.read_text()
    assert json.loads((paths.development / "service.json").read_text())["release_id"] == sha
    assert any(args[0] == "uv" for args, _ in fake.calls)
    assert not any(args[0] == "setpriv" for args, _ in fake.calls)
    assert any(args[:2] == ["git", "clone"] for args, _ in fake.calls)
    assert any(args[:4] == ["runuser", "-u", "acdev", "--"] for args, _ in fake.calls)
    migration = sandbox_steps(fake)[0]
    assert migration[-3:] == [str(paths.backend / ".venv/bin/alembic"), "upgrade", "head"]
    uv_calls = [(args, kwargs) for args, kwargs in fake.calls if args[0] == "uv"]
    assert uv_calls and all(kwargs["env"] == refresh.UV_ENV for _, kwargs in uv_calls)
    assert refresh.UV_ENV["UV_PYTHON_DOWNLOADS"] == "never"
    assert refresh.UV_ENV["UV_PYTHON_PREFERENCE"] == "only-system"
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    assert json.loads(output)["health"]["ok"]
    assert fake.health_calls == 4
    assert all(
        args[-1] == "http://127.0.0.1:8100/health/ready"
        for args, _ in fake.calls
        if args[0] == "curl"
    )
    assert "secret" not in output and "postgresql://" not in output
    # All three units restart only after the migration, in a fixed order.
    assert restarts(fake) == list(UNIT_ORDER)
    migrate_at = next(
        i
        for i, (args, _) in enumerate(fake.calls)
        if args[0] == "systemd-run" and args[-2:] == ["upgrade", "head"]
    )
    first_restart = next(
        i for i, (args, _) in enumerate(fake.calls) if args[:2] == ["systemctl", "restart"]
    )
    assert migrate_at < first_restart
    assert json.loads(output)["restarted"] == list(UNIT_ORDER)
    calls = len(fake.calls)
    noop = refresh.refresh(paths, fake, uid=0)
    assert noop["noop"]
    assert not any(args[0] in ("uv", "systemd-run", "systemctl") for args, _ in fake.calls[calls:])


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
    paths.migrator_env.write_text(
        "AC_ENVIRONMENT=staging\nAC_DATABASE_MIGRATOR_URL=postgresql://fake\n"
    )
    paths.migrator_env.chmod(0o600)
    with pytest.raises(refresh.RefreshError, match="development_environment_required"):
        refresh.refresh(paths, FakeCommands(sha), uid=0)
    assert not paths.backend.exists()


def test_missing_uv_refuses_before_backend_changes(tree, monkeypatch):
    paths, sha, _, _ = tree
    real_which = shutil.which

    def without_uv(name, path=None):
        if name == "uv":
            return None
        return real_which(name, path=path)

    monkeypatch.setattr(refresh.shutil, "which", without_uv)
    with pytest.raises(refresh.RefreshError, match="uv_missing"):
        refresh.refresh(paths, FakeCommands(sha), uid=0)
    assert not paths.backend.exists()


def test_migrator_url_in_api_env_refuses_before_backend_changes(tree):
    paths, sha, _, _ = tree
    (paths.development / "api.env").write_text(
        "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL=postgresql://fake\n"
    )
    with pytest.raises(refresh.RefreshError, match="migrator_url_in_api_env"):
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
    failed.units = dict.fromkeys(failed.units, "active")
    with pytest.raises(refresh.RefreshError, match="api_restart_failed"):
        refresh.refresh(paths, failed, uid=0)
    assert git("-C", str(paths.backend), "rev-parse", "HEAD") == old
    assert (paths.backend / ".ac-release-id").read_bytes() == old_marker
    assert paths.api_dropin.read_bytes() == old_api
    assert paths.worker_dropin.read_bytes() == old_worker
    assert (paths.development / "service.json").read_bytes() == old_manifest
    rollback_sync = [kwargs for args, kwargs in failed.calls if args[0] == "uv"]
    assert rollback_sync and all(kwargs["env"] == refresh.UV_ENV for kwargs in rollback_sync)
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err
    result = json.loads(captured.out.splitlines()[-1])
    assert result["error"] == "api_restart_failed" and result["restarted"] == "rollback_attempted"
    assert result["phase"] == "restart" and result["exit_status"] == 1
    assert result["previous"] == old and result["rollback"]["ok"]
    assert result["rollback"]["units"] == dict.fromkeys(failed.units, "restarted")
    assert failed.units == dict.fromkeys(failed.units, "active")
    # The failed API restart stops the forward pass; rollback restarts all three units.
    assert restarts(failed) == ["ac-dev-api.service", *UNIT_ORDER]


def test_health_timeout_rolls_back_checkout_and_release_state(tree, capsys, monkeypatch):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    fake.health_failures = 100
    monkeypatch.setattr(refresh, "HEALTH_WAIT_SECONDS", 0)
    with pytest.raises(refresh.RefreshError, match="health_release_mismatch"):
        refresh.refresh(paths, fake, uid=0)
    assert fake.health_calls == 1
    assert not paths.backend.exists()
    assert not paths.api_dropin.exists()
    assert not paths.worker_dropin.exists()
    assert not (paths.development / "service.json").exists()
    output = capsys.readouterr().out
    result = json.loads(output.splitlines()[-1])
    assert result["error"] == "health_release_mismatch"
    assert result["restarted"] == "rollback_attempted"
    assert result["previous"] is None and result["migrated"] == "yes"
    assert result["rollback"]["units"] == dict.fromkeys(fake.units, "stopped")
    assert fake.units == dict.fromkeys(fake.units, "inactive")


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
    expected_script = SCRIPT.relative_to(ROOT / "infra/application")
    expected_exec = "/srv/authority-closers/application/current-staging/" + str(expected_script)
    assert f"ExecStart=/usr/bin/python3 {expected_exec}" in service
    assert expected_script == Path("scripts/refresh-dev-sales-xray-backend.py")
    assert "UMask=0022" in service
    assert (
        git(
            "ls-files",
            "--error-unmatch",
            "infra/application/scripts/refresh-dev-sales-xray-backend.py",
        )
        == "infra/application/scripts/refresh-dev-sales-xray-backend.py"
    )
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


def failure_report(capsys) -> dict:
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err
    return json.loads(captured.out.splitlines()[-1])


def test_first_install_migrates_as_10001_behind_protected_ancestor(tree, tmp_path):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    refresh.refresh(paths, fake, uid=0)
    migration, smoke = sandbox_steps(fake)
    properties = [migration[i + 1] for i, item in enumerate(migration) if item == "--property"]
    # uid 10001 never traverses root:acops 2750 /srv/authority-closers: it is
    # masked by a read-only tmpfs and only the backend is bound back, read-only.
    assert "TemporaryFileSystem=/srv/authority-closers:ro /run/ac-sales-xray:ro" in " ".join(
        properties
    )
    assert f"BindReadOnlyPaths={paths.backend}" in properties
    assert f"WorkingDirectory={paths.backend}" in properties
    assert f"EnvironmentFile={paths.migrator_env}" in properties
    assert "User=10001" in properties and "Group=10001" in properties
    assert not any(
        item.startswith(("SupplementaryGroups", "DynamicUser", "User=root", "Group=acops"))
        for item in properties
    )
    assert "--unit=ac-dev-sales-xray-migrate.service" in migration
    assert "--unit=ac-dev-sales-xray-smoke.service" in smoke
    # The DSN stays in the root-only file: not in any argv or child environment.
    for args, kwargs in fake.calls:
        assert not any("secret" in item or "postgresql://" in item for item in args)
        assert "AC_DATABASE_MIGRATOR_URL" not in (kwargs.get("env") or {})
    # The step's executable is the backend's own Alembic, run only via the unit.
    assert not any(args[0] == str(paths.backend / ".venv/bin/alembic") for args, _ in fake.calls)
    systemd_analyze = shutil.which("systemd-analyze")
    if systemd_analyze:
        unit = tmp_path / "rendered-migrate.service"
        unit.write_text(
            "[Service]\nType=exec\n"
            + "".join(item + "\n" for item in properties)
            + "ExecStart=/usr/bin/true\n"
        )
        result = subprocess.run(  # noqa: S603 - fixed local parser command
            [systemd_analyze, "verify", str(unit)], capture_output=True, check=False
        )
        assert result.returncode == 0, result.stderr.decode()


def test_sandbox_matches_development_api_unit():
    api = (ROOT / "infra/application/development/ac-dev-api.service").read_text().splitlines()
    for item in refresh.SANDBOX_PROPERTIES:
        if item.split("=", 1)[0] in ("StandardInput", "StandardOutput", "StandardError"):
            continue
        if item.startswith("TasksMax="):
            assert item == "TasksMax=64"
            continue
        assert item in api, item


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"missing": True}, "runtime_identity_missing"),
        ({"groups": (10001, 1002)}, "runtime_identity_invalid"),
        ({"name": "someone-else"}, "runtime_identity_invalid"),
    ],
)
def test_runtime_identity_admission_refuses_before_any_change(tree, monkeypatch, kwargs, code):
    paths, sha, _, _ = tree
    identity(monkeypatch, **kwargs)
    fake = FakeCommands(sha)
    with pytest.raises(refresh.RefreshError, match=code):
        refresh.refresh(paths, fake, uid=0)
    assert not paths.backend.exists() and not paths.backend.parent.exists()
    assert not any(args[0] in ("systemctl", "systemd-run", "uv") for args, _ in fake.calls)
    assert not any(args[:2] == ["git", "clone"] for args, _ in fake.calls)


def test_migrator_env_extra_key_refuses(tree):
    paths, sha, _, _ = tree
    paths.migrator_env.write_text(
        "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL=postgresql://user:secret@dev/db\n"
        "PYTHONPATH=/tmp\n"
    )
    with pytest.raises(refresh.RefreshError, match="migrator_env_keys_invalid"):
        refresh.refresh(paths, FakeCommands(sha), uid=0)
    assert not paths.backend.exists()


@pytest.mark.parametrize(
    ("fail", "phase", "code", "status"),
    [
        ("clone", "clone", "clone_failed", 128),
        ("uv", "dependencies", "dependency_sync_failed", 2),
        ("migration", "migration", "migration_failed", 1),
    ],
)
def test_first_install_failure_before_migration_restores_absent_state(
    tree, capsys, fail, phase, code, status
):
    paths, sha, _, _ = tree
    profile = paths.development / "service.json"
    profile.write_text("existing secure profile\n")
    profile.chmod(0o600)
    fake = FakeCommands(sha)
    fake.fail.add(fail)
    with pytest.raises(refresh.RefreshError, match=code) as raised:
        refresh.refresh(paths, fake, uid=0)
    assert raised.value.exit_status == status
    result = failure_report(capsys)
    assert result["previous"] is None and result["migrated"] == "no"
    assert (result["phase"], result["error"], result["exit_status"]) == (phase, code, status)
    assert result["rollback"] == {
        "ok": True,
        "failed": [],
        "units": dict.fromkeys(fake.units, "stopped"),
    }
    assert result["units_before"] == dict.fromkeys(fake.units, "inactive")
    assert not paths.backend.exists() and not paths.backend.parent.exists()
    assert not paths.api_dropin.exists() and not paths.api_dropin.parent.exists()
    assert not paths.worker_dropin.exists() and not paths.worker_dropin.parent.exists()
    assert profile.read_text() == "existing secure profile\n"
    assert paths.migrator_env.exists() and (paths.development / "api.env").exists()
    # Nothing is started without a backend, so no unit can enter a restart loop.
    assert not any(cmd[0] in ("restart", "start") for cmd in systemctl(fake))
    assert fake.units == dict.fromkeys(fake.units, "inactive")


def test_first_install_restart_failure_with_no_previous_stops_units(tree, capsys):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    fake.fail_api_restart = True
    fake.restart_status = 217
    with pytest.raises(refresh.RefreshError, match="api_restart_failed"):
        refresh.refresh(paths, fake, uid=0)
    result = failure_report(capsys)
    assert (result["phase"], result["exit_status"], result["migrated"]) == ("restart", 217, "yes")
    assert result["previous"] is None and result["rollback"]["ok"]
    commands = systemctl(fake)
    failed_at = commands.index(["restart", "ac-dev-api.service"])
    assert ["stop", "ac-dev-sales-xray-worker.service"] in commands[failed_at:]
    assert ["stop", "ac-dev-api.service"] in commands[failed_at:]
    assert ["reset-failed", "ac-dev-api.service"] in commands[failed_at:]
    assert not any(cmd[0] in ("restart", "start") for cmd in commands[failed_at + 1 :])
    assert fake.units == dict.fromkeys(fake.units, "inactive")
    assert not paths.backend.exists()
    assert not (paths.development / "service.json").exists()


def test_unstoppable_unit_keeps_checkout_and_reports_rollback_failed(tree, capsys):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    fake.fail_api_restart = True
    fake.fail.add("stop")
    with pytest.raises(refresh.RefreshError, match="rollback_failed"):
        refresh.refresh(paths, fake, uid=0)
    result = failure_report(capsys)
    assert result["error"] == "api_restart_failed" and not result["rollback"]["ok"]
    assert "remove_checkout" in result["rollback"]["failed"]
    assert paths.backend.exists()


def test_main_prints_only_stable_code(tree, capsys, monkeypatch):
    paths, sha, _, _ = tree
    fake = FakeCommands(sha)
    fake.fail.add("migration")
    monkeypatch.setattr(refresh, "Paths", lambda: paths)
    monkeypatch.setattr(refresh, "command", fake)
    monkeypatch.setattr(refresh.os, "geteuid", lambda: 0)
    monkeypatch.setattr(refresh.refresh, "__defaults__", (fake,))
    assert refresh.main([]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "migration_failed"
    assert "secret" not in captured.out + captured.err

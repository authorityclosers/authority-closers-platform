"""Release train failure paths, using no network, database, service or paid AI."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tests.infra.test_ac_release import (
    DIGEST,
    HEAD,
    MODULE,
    OLD,
    OUTSIDE,
    FakeRunner,
    promotion_setup,
    release_event,
)

NOW = dt.datetime(2026, 9, 30, 3, tzinfo=dt.UTC).timestamp()
PAIR = (HEAD, HEAD)


def smoke_record(
    engine, environment, *, result="pass", age=0, corrupt=False, omit=None, overrides=None
):
    path = engine.paths.state / "smoke" / environment / ("-".join(PAIR) + ".json")
    record = {
        "result": result,
        "environment": environment,
        "core_sha": HEAD,
        "web_sha": HEAD,
        "spend": 0,
        **(overrides or {}),
    }
    if omit:
        record.pop(omit)
    digest = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    record["digest"] = "0" * 64 if corrupt else digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    os.utime(path, (NOW - age, NOW - age))
    return "sha256:" + digest


def dump_record(engine, name, *, area="logical", age=0, size=40):
    path = engine.paths.backups / area / name / "backup.dump"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"d" * size)
    path.with_name("metadata.json").write_text(
        json.dumps(
            {
                "environment": "production",
                "release_id": OLD,
                "dump_bytes": size,
                "dump_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    )
    os.utime(path, (NOW - age, NOW - age))
    return path


class TrainRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.ancestors.add((OLD, HEAD))
        self.restore = dict(
            LoadState="loaded",
            ActiveState="inactive",
            Result="success",
            ExecMainCode="1",
            ExecMainStatus="0",
            ExecMainExitTimestamp="Wed 2026-09-30 02:00:00 UTC",
        )
        self.smoke_result = {"staging": "pass", "production": "pass"}
        self.verdict = "additive"
        self.dump_failure = None
        self.events = []
        self.engine = None
        self.smoke_omit = None
        self.smoke_overrides = None
        self.notify_failure = None

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        out, code = "", 0
        if argv[:2] == ["systemctl", "show"]:
            assert argv[2] == "ac-restic-postgres-restore-proof@production.service"
            out = "\n".join(f"{k}={v}" for k, v in self.restore.items())
        elif argv[0] == "ac-train-notify":
            self.events.append(argv)
            if self.notify_failure == "exception":
                raise OSError("fake notification failure")
            if self.notify_failure == "exit":
                code = 1
        elif any(a.endswith("/ac_smoke.py") for a in argv):
            environment = argv[2]
            outcome = self.smoke_result[environment]
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(argv, 1560)
            if outcome == "busy":
                code = 5
            else:
                smoke_record(
                    self.engine,
                    environment,
                    result=outcome,
                    omit=self.smoke_omit,
                    overrides=self.smoke_overrides,
                )
                code = 0 if outcome == "pass" else 1
        elif any(a.endswith("/migration_safety.py") for a in argv):
            out = json.dumps({"verdict": self.verdict})
            code = 0 if self.verdict == "additive" else 3
        elif argv[0] == "ac-postgres-backup":
            assert argv == ["ac-postgres-backup", "--environment", "production", "--capture-only"]
            if self.dump_failure != "missing":
                dump_record(
                    self.engine,
                    "20260930T030000.000000Z-123-production",
                    age=2000 if self.dump_failure == "stale" else 0,
                )
        elif argv[:2] == ["bash", "-c"]:
            assert "pg_restore --list" in argv[2] and "--clean" not in argv[2]
            if self.dump_failure == "list":
                raise MODULE.ReleaseError("pg_restore exited with 1")
        else:
            return super().__call__(argv, **kwargs)
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, code, out, "")


@pytest.fixture
def train(tmp_path):
    engine, _, core, web = promotion_setup(tmp_path, production_core=OLD, production_web=OUTSIDE)
    engine.paths = replace(engine.paths, backups=tmp_path / "backups", engine=tmp_path / "engine")
    engine.clock = lambda: NOW
    runner = TrainRunner()
    runner.engine = engine
    engine.run = runner
    engine.github = None
    core["development"] = HEAD
    (engine.paths.config / "train.enabled").touch()
    engine.append_release(release_event("v0.2.0", OLD, OUTSIDE))
    for sha in (HEAD, OLD):
        release = engine.paths.application / "releases" / sha
        release.mkdir(parents=True)
        (release / "release-images.env").write_text("AC_MIGRATION_HEAD=20260929_0052\n")
    provenance = engine.paths.store / OLD / "core.provenance.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text(
        json.dumps(dict(run_id=90, artifact_id=6, artifact_name="old", artifact_digest=DIGEST))
    )
    dump_record(engine, "20260930T020000.000000Z-122-production", age=3600)
    source = tmp_path / "source"
    source.mkdir()

    @contextlib.contextmanager
    def source_for(sha):
        assert sha == HEAD
        yield source

    engine.train_source = source_for

    def deploy_core(environment, build, **kwargs):
        core[environment] = build.sha
        return {"previous": OLD}

    engine.deploy_core = deploy_core

    def deploy_web(environment, build, **kwargs):
        web[environment] = build.sha
        return {"previous": OUTSIDE}

    engine.deploy_web = deploy_web
    engine.prune_store = lambda: []

    def rollback_web(environment):
        web[environment] = OUTSIDE
        return {"restored_sha": OUTSIDE}

    engine.rollback_web = rollback_web
    return engine, runner, core, web


def calls(runner, text):
    return [call for call in runner.calls if any(text in a for a in call)]


@pytest.mark.parametrize(
    ("gate", "reason", "alert"),
    [
        ("production", "production_disabled", False),
        ("train", "train_disabled", False),
        ("pause", "production_paused", True),
        ("core-failed", "production_failed", True),
        ("web-failed", "production_failed", True),
        ("restore", "restore_check_failed", True),
    ],
)
def test_train_gates(train, gate, reason, alert):
    engine, runner, _, _ = train
    if gate in ("production", "train"):
        (engine.paths.config / f"{gate}.enabled").unlink()
    elif gate == "pause":
        engine.set_paused("production", True)
    elif gate.endswith("failed"):
        engine.paths.failed_flag("production", gate.split("-")[0]).touch()
    else:
        runner.restore = {}
    assert engine.train(now=True)["reason"] == reason
    assert bool([e for e in runner.events if e[1] == "alert"]) == alert
    assert not calls(runner, "ac_smoke") and not calls(runner, "ac-postgres-backup")
    assert not calls(runner, "fetch")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("Result", "exit-code"),
        ("ExecMainStatus", "1"),
        ("ExecMainCode", "2"),
        ("LoadState", "not-found"),
        ("ActiveState", "activating"),
        ("ExecMainExitTimestamp", ""),
        ("ExecMainExitTimestamp", "Mon 2026-09-21 03:00:00 UTC"),
        ("ExecMainExitTimestamp", "Wed 2026-09-30 04:00:00 UTC"),
    ],
)
def test_restore_proof_fails_closed(train, key, value):
    engine, runner, _, _ = train
    assert engine.restore_check_ok()
    runner.restore[key] = value
    assert not engine.restore_check_ok()


def test_nothing_to_ship_is_quiet(train):
    engine, runner, core, web = train
    core["production"] = web["production"] = HEAD
    before = engine.paths.history.read_bytes()
    assert engine.train() == {"result": "nothing_to_ship"}
    assert not runner.events and not calls(runner, "ac_smoke")
    assert not calls(runner, "ac-postgres-backup")
    assert engine.paths.history.read_bytes() == before


def test_train_success_preserves_smoke_evidence_and_one_logical_release(train):
    engine, runner, core, web = train
    assert engine.train()["result"] == "promoted"
    assert core["production"] == web["production"] == HEAD
    current, previous = engine.production_releases()
    assert current["version"] == "v0.2.1" and previous["version"] == "v0.2.0"
    assert current["requested_by"] == "standing-approval:AUT-72@2026-09-29T19:05Z"
    assert all(MODULE.DIGEST_RE.fullmatch(d) for d in current["smoke"].values())
    assert len(engine.release_records()) == 3  # original, promote, smoke supersession
    assert len(list((engine.paths.state / "train-smoke").glob("*.json"))) >= 1
    assert [e[1] for e in runner.events] == ["status"]
    assert len(calls(runner, "ac_smoke.py")) == 2


@pytest.mark.parametrize(
    ("age", "corrupt", "reused"), [(0, False, True), (21600, False, False), (0, True, False)]
)
def test_smoke_cache_is_pair_digest_and_time_bound(train, age, corrupt, reused):
    engine, runner, _, _ = train
    smoke_record(engine, "staging", age=age, corrupt=corrupt)
    assert engine.train()["result"] == "promoted"
    assert len(calls(runner, "ac_smoke.py")) == (1 if reused else 2)


@pytest.mark.parametrize("outcome", ["fail", "timeout", "busy", "skipped"])
def test_staging_smoke_failure_is_permanent_for_pair(train, outcome):
    engine, runner, _, _ = train
    runner.smoke_result["staging"] = outcome
    assert engine.train()["reason"] == "staging_smoke_failed"
    count = len(runner.calls)
    runner.smoke_result["staging"] = "pass"
    assert engine.train()["reason"] == "train_failed"
    assert not any("ac_smoke.py" in " ".join(c) for c in runner.calls[count:])
    assert not calls(runner, "ac-postgres-backup")
    assert [e[1] for e in runner.events] == ["alert", "status"]


@pytest.mark.parametrize("verdict", ["unknown", "destructive"])
def test_nonadditive_migration_needs_supervision_without_marking_pair(train, verdict):
    engine, runner, _, _ = train
    runner.verdict = verdict
    assert engine.train()["reason"] == "needs supervised promote"
    assert not (engine.paths.state / "train-failed").exists()
    assert not calls(runner, "ac-postgres-backup")


@pytest.mark.parametrize("failure", ["missing", "stale", "list"])
def test_dump_failures_prevent_promotion(train, failure):
    engine, runner, core, _ = train
    runner.dump_failure = failure
    assert engine.train()["result"] == "failed"
    assert core["production"] == OLD
    assert len(engine.release_records()) == 1
    assert not (engine.paths.backups / "train").exists()


def test_disk_failure_happens_before_capture(train, monkeypatch):
    engine, runner, _, _ = train
    monkeypatch.setattr(MODULE.shutil, "disk_usage", lambda _: type("Disk", (), {"free": 79})())
    assert engine.train()["reason"] == "dump_disk_low"
    assert not calls(runner, "ac-postgres-backup")


def test_train_dump_ring_retains_three_without_pruning_regular_backups(train):
    engine, _, _, _ = train
    for day in range(25, 30):
        dump_record(
            engine, f"202609{day}T020000.000000Z-122-production", area="train", age=9000 - day
        )
    engine.train_dump()
    assert len(list((engine.paths.backups / "train").glob("*/backup.dump"))) == 3
    assert len(list((engine.paths.backups / "logical").glob("*/backup.dump"))) == 2


@pytest.mark.parametrize("changed_head", [False, True])
def test_prod_smoke_failure_rolls_back_only_compatible_core_and_pauses(train, changed_head):
    engine, runner, core, web = train
    if changed_head:
        (engine.paths.application / "releases" / HEAD / "release-images.env").write_text(
            "AC_MIGRATION_HEAD=20260930_0053\n"
        )
    runner.smoke_result["production"] = "fail"
    result = engine.train()
    assert result["result"] == "rolled_back"
    assert result["core"] == ("skipped: migration head changed" if changed_head else "restored")
    assert core["production"] == (HEAD if changed_head else OLD)
    assert web["production"] == OUTSIDE and engine.is_paused("production")
    assert engine.release_records()[-1]["rolled_back_from"] == "v0.2.1"
    assert engine.release_records()[-1]["action"] == "rollback"
    assert any("severity=critical" in event for event in runner.events)
    engine.set_paused("production", False)
    assert engine.train()["reason"] == "train_failed"


def test_web_rollback_failure_does_not_prevent_core_attempt_or_pause(train):
    engine, runner, core, _ = train
    runner.smoke_result["production"] = "timeout"
    engine.rollback_web = lambda _: (_ for _ in ()).throw(MODULE.ReleaseError("web failed"))
    result = engine.train()
    assert result["result"] == "rolled_back" and result["web"].startswith("failed")
    assert core["production"] == OLD and engine.is_paused("production")


def test_promote_refuses_moved_pair_before_attempt(train):
    engine, _, core, _ = train
    with pytest.raises(MODULE.ReleaseError, match="staging_moved"):
        engine.promote("patch", "v0.2.1", requested_by="test", trigger="test", pair=(OLD, HEAD))
    assert core["production"] == OLD


def test_dry_run_checks_migration_and_disk_without_writes_or_smoke(train):
    engine, runner, _, _ = train
    before = {p: p.read_bytes() for p in engine.paths.state.rglob("*") if p.is_file()}
    assert engine.train(dry_run=True)["result"] == "dry-run"
    after = {p: p.read_bytes() for p in engine.paths.state.rglob("*") if p.is_file()}
    assert before == after
    assert calls(runner, "migration_safety.py")
    assert not calls(runner, "ac_smoke.py") and not calls(runner, "ac-postgres-backup")
    assert not calls(runner, "fetch") and not runner.events


def test_lock_nesting_keeps_other_engine_out(train):
    engine, _, _, _ = train
    other = MODULE.Engine(paths=engine.paths)
    with engine.locked(wait=True), engine.locked(wait=True), other.locked(wait=False) as acquired:
        assert not acquired
    with other.locked(wait=False) as acquired:
        assert acquired


def test_core_rollback_staging_uses_previous_success_not_failed_or_latest_retry(train):
    engine, _, core, _ = train
    engine.paths.history.unlink()
    for sha, result in (
        (OLD, "success"),
        (OUTSIDE, "failed"),
        (HEAD, "success"),
        (HEAD, "success"),
    ):
        engine.record(dict(environment="staging", component="core", sha=sha, result=result))
    engine.rollback_core("staging")
    assert core["staging"] == OLD
    assert engine.history()[-1]["action"] == "rollback"


def test_old_ledger_remains_valid_and_bad_smoke_is_refused():
    assert MODULE._validate_release_record(release_event("v0.2.0"))
    with pytest.raises(MODULE.ReleaseError, match="smoke"):
        MODULE._validate_release_record({**release_event("v0.2.0"), "smoke": {"staging": "bad"}})


def test_status_exposes_train_restore_last_and_staging_target(train):
    engine, _, _, _ = train
    assert engine.train()["result"] == "promoted"
    status = engine.status()
    assert status["train"]["enabled"] and status["restore_check_ok"]
    assert status["last_train"]["result"] == "promoted"
    assert status["staging_pick"] == {"core": HEAD, "web": HEAD}


def test_timer_and_service_contract():
    root = Path(__file__).resolve().parents[2]
    timer = (root / "infra/release/systemd/ac-release-train.timer").read_text()
    service = (root / "infra/release/systemd/ac-release-train.service").read_text()
    assert "OnCalendar=*-*-* 00/2:15:00" in timer and "Persistent=false" in timer
    assert "TimeoutStartSec=5400" in service and "Restart=" not in service
    assert "MemoryMax=" in service


def test_interrupted_train_pauses_before_nothing_to_ship_and_resume_marks_pair_failed(train):
    engine, runner, core, web = train
    core["production"] = web["production"] = HEAD
    engine.train_state("train-inflight.json", {"pair": list(PAIR)})
    assert engine.train()["reason"] == "train_interrupted"
    assert engine.is_paused("production") and not calls(runner, "ac_smoke")
    engine.set_paused("production", False)
    assert not (engine.paths.state / "train-inflight.json").exists()
    assert (engine.paths.state / "train-failed" / ("-".join(PAIR) + ".json")).exists()


def test_final_kill_switch_refuses_after_dump_before_promote(train):
    engine, _, core, _ = train
    original = engine.train_dump

    def dump_and_disable():
        path = original()
        (engine.paths.config / "train.enabled").unlink()
        return path

    engine.train_dump = dump_and_disable
    assert engine.train()["reason"] == "train_disabled"
    assert core["production"] == OLD and len(engine.release_records()) == 1


def test_moved_staging_after_smoke_never_promotes(train):
    engine, _, core, _ = train
    original = engine.train_dump

    def dump_and_move():
        path = original()
        core["staging"] = OLD
        return path

    engine.train_dump = dump_and_move
    assert engine.train()["result"] == "failed"
    assert core["production"] == OLD and len(engine.release_records()) == 1


def test_failed_promotion_pauses_and_prevents_retry(train):
    engine, _, _, _ = train
    engine.deploy_core = lambda *_a, **_k: (_ for _ in ()).throw(
        MODULE.ReleaseError("installer failed")
    )
    assert engine.train()["reason"] == "promotion_failed"
    assert engine.is_paused("production")
    engine.set_paused("production", False)
    assert engine.train()["reason"] == "train_failed"


def test_manual_core_rollback_failure_pauses_environment(train):
    engine, _, _, _ = train
    engine.record(dict(environment="staging", component="core", sha=OLD, result="success"))
    engine.record(dict(environment="staging", component="core", sha=HEAD, result="success"))
    engine.deploy_core = lambda *_a, **_k: (_ for _ in ()).throw(MODULE.ReleaseError("failed"))
    with pytest.raises(MODULE.ReleaseError):
        engine.rollback_core("staging")
    assert engine.is_paused("staging")


@pytest.mark.parametrize("failure", ["none", "schema", "identity", "api", "worker"])
def test_application_only_rollback_never_reaches_database_commands(tmp_path, failure):
    import shlex

    installer = (
        Path(__file__).resolve().parents[2]
        / "infra/application/scripts/install-application-release.sh"
    ).read_text()
    start = installer.index("core_rollback_exit() {")
    functions = installer[
        start : installer.index('if [[ "${AC_CORE_ROLLBACK_ONLY:-0}" == 1 ]]; then', start)
    ]
    old = tmp_path / OLD
    old.mkdir()
    (old / "release-images.env").write_text("AC_MIGRATION_HEAD=20260929_0052\n")
    app = tmp_path / "app"
    app.mkdir()
    log = tmp_path / "operations.log"
    backup = tmp_path / "unused.dump"
    backup.touch()
    variables = {
        "previous_release": str(old),
        "AC_ROLLBACK_FROM": OUTSIDE if failure == "identity" else OLD,
        "AC_MIGRATION_HEAD": "20260930_0053" if failure == "schema" else "20260929_0052",
        "target_environment": "staging",
        "release_id": HEAD,
        "application_root": str(app),
        "release_dir": str(tmp_path / HEAD),
        "current_link": str(app / "current-staging"),
        "edge_hold_source": "hold",
        "edge_route_source": "route",
        "api_host": "fake.invalid",
        "backup_file": str(backup),
        "TEST_LOG": str(log),
        "TEST_FAILURE": failure,
    }
    harness = "set -euo pipefail\n" + "\n".join(
        f"{k}={shlex.quote(v)}" for k, v in variables.items()
    )
    harness += r"""
trace() { printf '%s\n' "$*" >> "$TEST_LOG"; }
activate_edge_route() { trace "route $*"; }
check_route() { trace "check $*"; }
stop_application_services_with_hosted_drain() { trace "stop $*"; }
cleanup_stages() { trace cleanup; }
sales_xray_hosted_enabled() { return 0; }
chown() { :; }
install() { mkdir -p "${@: -1}"; }
compose_for() {
  trace "compose $*"
  if [[ "$TEST_FAILURE" == api && " $* " == *' api '* ]]; then return 8; fi
  if [[ "$TEST_FAILURE" == worker && " $* " == *' worker '* ]]; then return 8; fi
}
"""
    harness += functions + "\nrollback_application_only\n"
    completed = subprocess.run(
        ["/bin/bash", "-s"], input=harness, text=True, capture_output=True, check=False
    )
    ops = log.read_text() if log.exists() else ""
    assert (completed.returncode == 0) == (failure == "none"), completed.stderr
    assert not any(
        word in ops for word in ("postgres", "pg_restore", "pg_dump", "migrate", "fence")
    )
    if failure in ("schema", "identity"):
        assert "compose" not in ops
    else:
        assert "--no-deps" in ops
    if failure in ("api", "worker"):
        assert "CORE_ROLLBACK_FAILED" in completed.stderr
        assert ops.count("route hold") == 2
    if failure == "none":
        assert (app / "current-staging").is_symlink()
        evidence = list((app / "deployments/staging").glob("*.env"))
        assert len(evidence) == 1 and "AC_ACTION=CORE_ROLLBACK" in evidence[0].read_text()


def test_core_only_train_keeps_unchanged_web_on_smoke_failure(train):
    engine, runner, core, web = train
    web["production"] = HEAD
    engine.paths.releases.unlink()
    engine.append_release(release_event("v0.2.0", OLD, HEAD))
    runner.smoke_result["production"] = "fail"
    engine.rollback_web = lambda _: pytest.fail("must not undo an unrelated prior web release")
    result = engine.train()
    assert result["web"] == "unchanged" and core["production"] == OLD
    assert web["production"] == HEAD


def test_prod_smoke_failure_records_the_actual_failed_smoke_digest(train):
    engine, runner, _, _ = train
    runner.smoke_result["production"] = "fail"
    engine.train()
    smoke = engine.paths.state / "smoke/production" / ("-".join(PAIR) + ".json")
    failed_digest = json.loads(smoke.read_text())["digest"]
    assert engine.release_records()[-1]["smoke"]["production"] == "sha256:" + failed_digest


def test_production_move_after_migration_check_prevents_promotion(train):
    engine, _, core, web = train
    original = engine.train_dump

    def dump_and_move_production():
        path = original()
        web["production"] = OLD
        return path

    engine.train_dump = dump_and_move_production
    assert engine.train()["reason"] == "production_moved"
    assert core["production"] == OLD and len(engine.release_records()) == 1


def test_status_preserves_local_state_when_github_is_unavailable(train):
    engine, _, _, _ = train

    class Unavailable:
        def get_json(self, *_args, **_kwargs):
            raise MODULE.ReleaseError("unavailable")

    engine.github = Unavailable()
    result = engine.status()
    assert result["staging_pick_error"] == "discovery_unavailable"
    assert result["environments"]["production"]["core"] == OLD


@pytest.mark.parametrize("target_active", [False, True])
def test_deploy_core_rollback_uses_installed_controller_not_old_installer(
    train, monkeypatch, target_active
):
    import io
    import tarfile

    engine, _, core, _ = train
    # Use the real deploy implementation with fake artifacts and installer process.
    monkeypatch.delattr(engine, "deploy_core")
    engine.installed_engine = lambda: HEAD
    bundle = engine.paths.store / OLD / "core"
    bundle.mkdir()
    for name in MODULE.CORE_FILES:
        (bundle / name).write_text("fake")
    engine.store_bundle = lambda *_: bundle
    engine.require_backup_support = lambda _: None
    core["production"] = HEAD
    current_activation = engine.activation_path("production", HEAD)
    current_activation.parent.mkdir(parents=True, exist_ok=True)
    current_activation.write_text('{"fixture": "current active release"}')
    target_activation = engine.activation_path("production", OLD)
    if target_active:
        target_activation.write_text('{"fixture": "historical activation"}')
    before = {p: p.read_bytes() for p in current_activation.parent.glob("*.json")}
    engine.keep_native_build = lambda _: pytest.fail("rollback must not acquire native builds")
    engine.prepare_activation = lambda *_a, **_k: pytest.fail("must not carry activation backward")
    engine.check_core = lambda *_: None
    selected = []

    def archive(sha, stage, prefix):
        selected.append(sha)
        path = stage / (sha + ".tar")
        with tarfile.open(path, "w") as tar:
            data = b"# AC_CORE_ROLLBACK_ONLY\n" if sha == HEAD else b"# old controller\n"
            entry = tarfile.TarInfo("infra/application/scripts/install-application-release.sh")
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        return path, "d" * 64

    engine.source_archive = archive
    installer_calls = []
    verified_archives = []

    def run(argv, **kwargs):
        if argv[0] == "python3":
            verified_archives.append(argv)
        if argv[0] == "bash":
            installer_calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "AC_STATUS=COMMITTED\n", "")

    engine.run = run
    build = engine.stored_build(OLD, "core")
    assert build is not None
    engine.deploy_core("production", build, rollback_only=True)
    assert {p: p.read_bytes() for p in current_activation.parent.glob("*.json")} == before
    assert target_activation.exists() == target_active
    assert selected == [OLD, HEAD]
    assert [call[-1] for call in verified_archives] == [OLD, HEAD]
    argv, kwargs = installer_calls[0]
    assert "/controller/" in argv[1]
    assert kwargs["env"]["AC_RELEASE_ID"] == OLD
    assert kwargs["env"]["AC_CORE_ROLLBACK_ONLY"] == "1"
    assert kwargs["env"]["AC_ROLLBACK_FROM"] == core["production"]
    assert (
        kwargs["env"]["AC_ROLLBACK_CONTROLLER_SHA256"]
        == hashlib.sha256(b"# AC_CORE_ROLLBACK_ONLY\n").hexdigest()
    )


@pytest.mark.parametrize("field", ["core_sha", "web_sha", "environment"])
@pytest.mark.parametrize("missing", [True, False])
def test_smoke_requires_matching_environment_and_both_pair_fields(train, field, missing):
    engine, runner, core, _ = train
    options = {"omit": field} if missing else {"overrides": {field: "wrong"}}
    smoke_record(engine, "staging", **options)
    runner.smoke_omit = options.get("omit")
    runner.smoke_overrides = options.get("overrides")
    assert engine.train()["reason"] == "staging_smoke_failed"
    assert len(calls(runner, "ac_smoke.py")) == 1  # Malformed cache was not reused.
    assert core["production"] == OLD and len(engine.release_records()) == 1
    assert not calls(runner, "ac-postgres-backup")


@pytest.mark.parametrize("outcome", ["pass", "fail"])
def test_every_train_release_retains_complete_audit_evidence(train, outcome):
    engine, runner, _, _ = train
    runner.smoke_result["production"] = outcome
    engine.train()
    records = engine.release_records()[1:]
    for record in records:
        evidence = record["train"]
        assert set(evidence) == {
            "core_sha",
            "web_sha",
            "artifacts",
            "patch_version",
            "migration",
            "dump",
            "restore",
            "promotion_outcome",
            "production_smoke",
            "rollback",
            "paused",
        }
        assert (evidence["core_sha"], evidence["web_sha"]) == PAIR
        assert evidence["artifacts"] == {"core": DIGEST, "web": DIGEST}
        assert evidence["patch_version"] == "v0.2.1"
        assert evidence["migration"] == {
            "from": "20260929_0052",
            "to": "20260929_0052",
            "classification": "additive",
        }
        dump = evidence["dump"]
        assert dump["bytes"] == Path(dump["path"]).stat().st_size == 40
        assert dump["sha256"] == hashlib.sha256(Path(dump["path"]).read_bytes()).hexdigest()
        assert evidence["restore"] == {
            "unit": "ac-restic-postgres-restore-proof@production.service",
            "exit_timestamp": runner.restore["ExecMainExitTimestamp"],
        }
        assert record["requested_by"] == "standing-approval:AUT-72@2026-09-29T19:05Z"
        assert evidence["promotion_outcome"] == "promoted"
        assert MODULE._validate_release_record(record) == record
    assert records[0]["train"]["production_smoke"] == "pending"
    assert records[0]["smoke"]["production"] is None  # Only evidence not available before mutation.
    assert records[-1]["train"]["production_smoke"] == outcome
    assert all(MODULE.DIGEST_RE.fullmatch(v) for v in records[-1]["smoke"].values())
    assert records[-1]["train"]["paused"] == (outcome == "fail")
    assert records[-1]["train"]["rollback"] == (
        {"core": "restored", "web": "restored"} if outcome == "fail" else {}
    )


@pytest.mark.parametrize(
    "missing",
    [
        "train",
        "smoke",
        "core_sha",
        "web_sha",
        "artifacts",
        "patch_version",
        "migration",
        "dump",
        "restore",
        "promotion_outcome",
        "production_smoke",
        "rollback",
        "paused",
    ],
)
def test_missing_evidence_refuses_before_production_mutation(train, missing):
    engine, _, core, web = train
    promote = engine.promote

    def omit_evidence(*args, **kwargs):
        if missing in ("train", "smoke"):
            kwargs.pop(missing)
        else:
            kwargs["train"].pop(missing)
        return promote(*args, **kwargs)

    engine.promote = omit_evidence
    assert engine.train()["reason"] == "train_evidence_invalid"
    assert core["production"] == OLD and web["production"] == OUTSIDE
    assert len(engine.release_records()) == 1
    assert not (engine.paths.state / "train-inflight.json").exists()


@pytest.mark.parametrize("failure", ["exit", "exception"])
@pytest.mark.parametrize("smoke", ["pass", "fail"])
def test_notifier_failure_preserves_release_outcome(train, failure, smoke):
    engine, runner, _, _ = train
    runner.notify_failure = failure
    runner.smoke_result["production"] = smoke
    expected = "promoted" if smoke == "pass" else "rolled_back"
    result = engine.train()
    assert result["result"] == expected
    assert result["notify_failed"] == (["status"] if smoke == "pass" else ["alert", "status"])
    assert json.loads((engine.paths.state / "last-train.json").read_text()) == result
    assert {e["result"] for e in engine.history() if e.get("action") == "train"} == {expected}
    assert not (engine.paths.state / "train-inflight.json").exists()


def test_two_staging_core_rollbacks_only_walk_successful_deploys_backwards(train):
    engine, _, core, _ = train
    engine.paths.history.unlink()
    for sha in (OUTSIDE, OLD, HEAD):
        release = engine.paths.application / "releases" / sha
        release.mkdir(exist_ok=True)
        (release / "release-images.env").write_text("AC_MIGRATION_HEAD=20260929_0052\n")
        provenance = engine.paths.store / sha / "core.provenance.json"
        provenance.parent.mkdir(exist_ok=True)
        if not provenance.exists():
            provenance.write_text((engine.paths.store / OLD / "core.provenance.json").read_text())
        engine.record(dict(environment="staging", component="core", sha=sha, result="success"))
    assert engine.rollback_core("staging")["restored_sha"] == OLD
    assert engine.rollback_core("staging")["restored_sha"] == OUTSIDE
    assert core["staging"] == OUTSIDE
    with pytest.raises(MODULE.ReleaseError):
        engine.rollback_core("staging")
    assert core["staging"] == OUTSIDE


@pytest.mark.parametrize("component", ["core", "web"])
def test_cli_rollback_records_history_once(train, monkeypatch, component):
    engine, _, _, _ = train
    assert engine.train()["result"] == "promoted"
    monkeypatch.setattr(MODULE, "Engine", lambda **_: engine)
    assert MODULE.main(["rollback", "production", "--component", component]) == 0
    entries = [e for e in engine.history() if e.get("action") == "rollback"]
    assert len(entries) == 1
    assert entries[0]["component"] == component


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("artifacts", "core"), "bad"),
        (("artifacts", "web"), None),
        (("dump", "path"), "relative.dump"),
        (("dump", "sha256"), "bad"),
        (("dump", "bytes"), 0),
        (("restore", "exit_timestamp"), ""),
        (("restore", "unit"), "staging-proof.service"),
        (("migration", "classification"), "destructive"),
        (("migration", "to"), None),
        (("patch_version",), "v5.0.0"),
        (("core_sha",), OLD),
        (("paused",), "false"),
        (("production_smoke",), "pass"),
        (("rollback",), {"core": "restored"}),
    ],
)
def test_malformed_train_evidence_is_rejected_before_deploy(train, path, value):
    engine, _, core, _ = train
    promote = engine.promote

    def corrupt_evidence(*args, **kwargs):
        target = kwargs["train"]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return promote(*args, **kwargs)

    engine.promote = corrupt_evidence
    assert engine.train()["reason"] == "train_evidence_invalid"
    assert core["production"] == OLD and len(engine.release_records()) == 1
    assert not (engine.paths.state / "train-inflight.json").exists()


@pytest.mark.parametrize("disabled", ["train", "production", "both"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_interrupted_train_containment_precedes_disabled_gates(train, disabled, dry_run):
    engine, runner, _, _ = train
    engine.train_state("train-inflight.json", {"pair": list(PAIR)})
    for flag in ("train", "production"):
        if disabled in (flag, "both"):
            (engine.paths.config / f"{flag}.enabled").unlink()
    result = engine.train(dry_run=dry_run)
    assert result["reason"] == "train_interrupted"
    assert engine.is_paused("production") is (not dry_run)
    assert (engine.paths.state / "train-inflight.json").exists()
    assert not calls(runner, "ac_smoke.py") and not calls(runner, "ac-postgres-backup")
    assert not calls(runner, "systemctl")
    if dry_run:
        assert not runner.events
    else:
        assert any("severity=critical" in event for event in runner.events)
        engine.set_paused("production", False)
        assert (engine.paths.state / "train-failed" / ("-".join(PAIR) + ".json")).exists()


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "missing_controller",
        "wrong_controller",
        "archive_digest",
        "commit",
        "unsafe",
        "normal_deploy",
    ],
)
def test_rollback_controller_verifies_and_stages_older_archive(tmp_path, failure):
    import shlex

    from tests.infra.test_application_release_archive import (
        INSTALLER,
        VERIFIER,
        _write_fixture_archive,
    )

    installer = INSTALLER.read_text()
    verification = installer[
        installer.index("verify_application_archive() {") : installer.index("\ngetent group acops")
    ]
    staging = installer[
        installer.index('if [[ -e "$release_dir" || -L "$release_dir" ]]; then') : installer.index(
            '\nsecret_environment="$target_environment"'
        )
    ]
    archive = tmp_path / "old.tar"
    # The old verifier is also different: both self-identity checks must survive.
    verifier = VERIFIER.read_bytes() + (
        b"\n# older exact-commit verifier\n" if failure != "normal_deploy" else b""
    )
    extra = [{"name": "infra/application/postgres/init/fixture.sql", "payload": b"-- fixture"}]
    if failure == "unsafe":
        extra.append({"name": "infra/application/../../escape", "payload": b"unsafe"})
    _write_fixture_archive(archive, commit=OLD, embedded_verifier=verifier, extra_members=extra)
    releases = tmp_path / "releases"
    releases.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    images = tmp_path / "release-images.env"
    images.write_text("AC_MIGRATION_HEAD=20260929_0052\n")
    variables = {
        "script_dir": str(INSTALLER.parent),
        "running_installer": str(INSTALLER),
        "release_archive": str(archive),
        "release_archive_sha256": "0" * 64
        if failure == "archive_digest"
        else hashlib.sha256(archive.read_bytes()).hexdigest(),
        "release_id": HEAD if failure == "commit" else OLD,
        "release_dir": str(releases / OLD),
        "releases_root": str(releases),
        "release_images_file": str(images),
        "input_stage": str(inputs),
        "AC_CORE_ROLLBACK_ONLY": "0" if failure == "normal_deploy" else "1",
        "AC_ROLLBACK_CONTROLLER_SHA256": ""
        if failure == "missing_controller"
        else (
            "0" * 64
            if failure == "wrong_controller"
            else hashlib.sha256(INSTALLER.read_bytes()).hexdigest()
        ),
    }
    harness = "set -euo pipefail\n" + "\n".join(
        f"{key}={shlex.quote(value)}" for key, value in variables.items()
    )
    harness += "\nchown() { :; }\n" + verification + "\nverify_application_archive\n" + staging
    completed = subprocess.run(
        ["/bin/bash", "-s"], input=harness, text=True, capture_output=True, check=False
    )
    assert (completed.returncode == 0) == (failure == "none"), completed.stderr
    target = releases / OLD
    if failure == "none":
        assert (target / "scripts/verify-release-archive.py").read_bytes() == verifier
        assert (
            target / "scripts/install-application-release.sh"
        ).read_bytes() != INSTALLER.read_bytes()
        assert (target / "RELEASE-COMMIT").read_text().strip() == OLD
        checked = subprocess.run(
            ["/usr/bin/sha256sum", "--check", "--strict", "RELEASE-FILES.sha256"],
            cwd=target,
            capture_output=True,
            check=False,
        )
        assert checked.returncode == 0
    else:
        assert not target.exists()
        message = {
            "missing_controller": "Rollback controller digest",
            "wrong_controller": "Rollback controller digest",
            "archive_digest": "Rollback target archive digest",
            "commit": "Git archive commit does not match",
            "unsafe": "unsafe path",
            "normal_deploy": "Running installer differs",
        }[failure]
        assert message in completed.stderr


@pytest.mark.parametrize("automatic", [False, True])
def test_repeated_production_core_rollback_never_redeploys_departed_core(train, automatic):
    engine, runner, core, _ = train
    if automatic:
        runner.smoke_result["production"] = "fail"
        assert engine.train()["result"] == "rolled_back"
    else:
        assert engine.train()["result"] == "promoted"
        assert engine.rollback_core("production")["restored_sha"] == OLD
    assert core["production"] == OLD
    before = engine.paths.releases.read_bytes()
    engine.deploy_core = lambda *_a, **_k: pytest.fail("must not redeploy departed core")
    with pytest.raises(MODULE.ReleaseError, match="core_rollback_target_departed"):
        engine.rollback_core("production")
    assert engine.paths.releases.read_bytes() == before and core["production"] == OLD


def test_production_core_rollback_keeps_previous_record_boundary_on_web_only_release(train):
    engine, _, core, web = train
    assert engine.train()["result"] == "promoted"
    web["production"] = OLD
    engine.append_release(release_event("v0.2.2", HEAD, OLD))
    engine.deploy_core = lambda *_a, **_k: pytest.fail("must not walk past previous release")
    before = engine.paths.releases.read_bytes()
    assert engine.rollback_core("production") == {"restored_sha": HEAD, "result": "unchanged"}
    assert engine.paths.releases.read_bytes() == before and core["production"] == HEAD

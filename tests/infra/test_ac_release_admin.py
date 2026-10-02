"""Admin release controls in the engine: snapshot, publishing, dry-run promote, pair rollback."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ac_release", ROOT / "infra/release/ac_release.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["ac_release"] = MODULE
SPEC.loader.exec_module(MODULE)
FIXTURES = ROOT / "tests/fixtures/release-control"

# Fictional commits: staging pair, production pair, previous production pair.
SC, SW, PC, PW, RC, RW = ("a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40, "f" * 40)
DIGEST = "sha256:" + "9" * 64
IMAGES = {sha: "sha256:" + sha[0] * 64 for sha in (SC, SW, PC, PW, RC, RW)}
# Keys whose contract value may be null where the fixture shows a value, or the reverse.
NULLABLE = {
    "engine.commit",
    "environments.*.version",
    "environments.*.core_sha",
    "environments.*.web_sha",
    "environments.*.core_deployed_at",
    "environments.*.web_deployed_at",
    "environments.*.failed_core",
    "environments.*.failed_web",
    "environments.*.approval_days_left",
    "releases.rolled_back_from",
    "staging_history.error",
    "promote.reason",
    "promote.core_sha",
    "promote.web_sha",
    "promote.commits_behind",
    "rollback.reason",
    "rollback.target_version",
    "rollback.core_sha",
    "rollback.web_sha",
    "busy",
}


class Runner:
    """Answers the git, docker and systemctl commands the snapshot issues."""

    def __init__(self, tags: list[str] | None = None) -> None:
        self.tags = tags or []
        self.ancestors = {(PC, SC), (RC, PC), (RC, SC), (SW, SC)}
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        self.calls.append(argv)
        out, code = "", 0
        if "for-each-ref" in argv:
            out = "".join(tag + "\n" for tag in self.tags)
        elif "rev-parse" in argv:
            out = SC + "\n"
        elif "merge-base" in argv:
            code = 0 if argv[-2] == argv[-1] or (argv[-2], argv[-1]) in self.ancestors else 1
        elif argv[:2] == ["systemctl", "show"]:
            code = 1
        elif not ("fetch" in argv or argv[:2] == ["git", "init"]):
            raise AssertionError(f"unexpected command {argv}")
        if kwargs.get("check", True) and code:
            raise MODULE.ReleaseError(f"{argv[0]} failed")
        return subprocess.CompletedProcess(argv, code, out, "")

    def fetches(self) -> int:
        return sum(1 for call in self.calls if "fetch" in call)


class NoGitHub:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the snapshot must not call GitHub ({name})")


def release(version: str, core: str, web: str, **extra: Any) -> dict[str, Any]:
    return {
        "version": version,
        "core_sha": core,
        "web_sha": web,
        "requested_by": "cli:root",
        "at": "2026-09-30T00:00:00Z",
        "action": "promote",
        "rolled_back_from": None,
        **extra,
    }


def setup(tmp_path: Path, *, tags: list[str] | None = None):
    runner = Runner(tags)
    paths = MODULE.Paths(
        state=tmp_path / "state",
        logs=tmp_path / "logs",
        store=tmp_path / "store",
        config=tmp_path / "config",
        application=tmp_path / "application",
        stage_root=tmp_path,
        lock=tmp_path / "lock",
        sales_xray=tmp_path / "sales-xray",
        engine=tmp_path / "engine",
    )
    for directory in (paths.state, paths.config, paths.mirror):
        directory.mkdir(parents=True)
    (paths.mirror / "HEAD").write_text("ref: refs/heads/main\n")
    paths.production_enabled.write_text("yes\n")
    engine = MODULE.Engine(paths=paths, github=NoGitHub(), run=runner, sleep=lambda _: None)
    core = {"staging": SC, "production": PC}
    web = {"staging": SW, "production": PW}
    engine.current_core = lambda environment: core[environment]
    engine.current_web = lambda environment: (web[environment], IMAGES.get(web[environment]))
    for sha in (SC, SW, PC, PW, RC, RW):
        for component in MODULE.COMPONENTS:
            provenance = paths.store / sha / f"{component}.provenance.json"
            provenance.parent.mkdir(parents=True, exist_ok=True)
            provenance.write_text(
                json.dumps(
                    {"run_id": 1, "artifact_id": 2, "artifact_name": "x", "artifact_digest": DIGEST}
                )
            )
        manifest = paths.application / "releases" / sha / "release-images.env"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("AC_MIGRATION_HEAD=20260930_0001\n")
    for component, sha in (("core", SC), ("web", SW)):
        engine.record(
            {
                "at": f"2026-10-01T08:4{int(component == 'web')}:00Z",
                "environment": "staging",
                "component": component,
                "sha": sha,
                "result": "success",
                "trigger": "auto",
            }
        )
    engine.record(
        {
            "at": "2026-09-30T16:12:00Z",
            "environment": "production",
            "component": "web",
            "sha": PW,
            "result": "success",
            "previous": RW,
            "previous_image": IMAGES[RW],
            "runtime_ref": IMAGES[PW],
        }
    )
    engine.append_release(release("v0.3.0", RC, RW))
    engine.append_release(release("v0.4.0", PC, PW))
    return engine, runner, core, web


def key_tree(value: Any, path: str = "") -> Any:
    if isinstance(value, dict):
        return {key: key_tree(item, f"{path}.{key}".lstrip(".")) for key, item in value.items()}
    if isinstance(value, list):
        return [key_tree(value[0], path)] if value else []
    return None


def assert_types(actual: Any, expected: Any, path: str = "") -> None:
    pattern = path.replace(".staging.", ".*.").replace(".production.", ".*.")
    if actual is None or expected is None:
        assert pattern in NULLABLE or actual is expected, path
    elif isinstance(expected, dict):
        assert set(actual) == set(expected), path
        for key in expected:
            assert_types(actual[key], expected[key], f"{path}.{key}".lstrip("."))
    elif isinstance(expected, list):
        assert isinstance(actual, list), path
        for item in actual:
            assert_types(item, expected[0], path)
    else:
        assert type(actual) is type(expected), path


@pytest.fixture(autouse=True)
def notes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def fake(git_dir, from_ref, to_sha):
        calls.append((git_dir, from_ref, to_sha))
        return [f"AUT-{n}: change (#{n})" for n in range(60, 0, -1)]

    monkeypatch.setattr(MODULE, "_release_notes", fake)
    return calls


# -- snapshot -------------------------------------------------------------------


def test_snapshot_has_exactly_the_contract_key_tree_and_types(
    tmp_path: Path, notes: list[tuple[Any, ...]]
) -> None:
    engine, runner, _, _ = setup(tmp_path, tags=["v0.2.9"])
    fixture = json.loads((FIXTURES / "status-v1.json").read_text())
    snapshot = engine.snapshot()
    assert key_tree(snapshot) == key_tree(fixture)
    assert_types(snapshot, fixture)
    assert snapshot["environments"]["production"]["version"] == "v0.4.0"
    assert snapshot["environments"]["staging"]["core_deployed_at"] == "2026-10-01T08:40:00Z"
    assert snapshot["environments"]["production"]["web_deployed_at"] == "2026-09-30T16:12:00Z"
    assert [entry["version"] for entry in snapshot["releases"]] == ["v0.4.0", "v0.3.0"]
    assert [entry["component"] for entry in snapshot["staging_history"]] == ["web", "core"]
    assert snapshot["promote"]["available"] is True
    assert (snapshot["promote"]["core_sha"], snapshot["promote"]["web_sha"]) == (SC, SW)
    assert notes == [(engine.paths.mirror, PC, SC)]
    assert snapshot["promote"]["commits_behind"] == 60
    assert len(snapshot["promote"]["notes"]) == MODULE.STATUS_NOTES_LIMIT
    assert snapshot["rollback"] == {
        "available": True,
        "reason": None,
        "target_version": "v0.3.0",
        "core_sha": RC,
        "web_sha": RW,
    }
    for name in ("request-v1.json", "outcome-v1.json"):
        assert json.loads((FIXTURES / name).read_text())["v"] == 1


def test_snapshot_reads_three_versions_from_one_mirror_sync(tmp_path: Path) -> None:
    engine, runner, _, _ = setup(tmp_path, tags=["v0.3.5", "nightly"])
    snapshot = engine.snapshot()
    assert snapshot["promote"]["next"] == {"patch": "v0.4.1", "minor": "v0.5.0", "major": "v1.0.0"}
    assert runner.fetches() == 1
    assert sum(1 for call in runner.calls if "for-each-ref" in call) == 1
    assert engine.next_version("minor") == "v0.5.0"


def test_snapshot_without_production_core_has_no_notes(
    tmp_path: Path, notes: list[tuple[Any, ...]]
) -> None:
    engine, _, core, web = setup(tmp_path)
    core["production"] = web["production"] = None
    promote = engine.snapshot()["promote"]
    assert (promote["commits_behind"], promote["notes"], notes) == (None, [], [])


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("disabled", "production deploys are not enabled on this server yet"),
        ("no_staging_web", "staging does not have a complete core and web pair"),
        ("already_running", "production already runs this staging pair"),
        ("not_forward", "production core is not an ancestor of the staging core"),
    ],
)
def test_each_promote_unavailable_reason(tmp_path: Path, change: str, reason: str) -> None:
    engine, runner, core, web = setup(tmp_path)
    if change == "disabled":
        engine.paths.production_enabled.unlink()
    elif change == "no_staging_web":
        web["staging"] = None
    elif change == "already_running":
        core["production"], web["production"] = SC, SW
    else:
        runner.ancestors.discard((PC, SC))
    promote = engine.snapshot()["promote"]
    assert (promote["available"], promote["reason"]) == (False, reason)


def test_snapshot_redacts_emails_and_reads_busy(tmp_path: Path) -> None:
    engine, _, _, _ = setup(tmp_path)
    engine.paths.releases.write_text(
        json.dumps(release("v0.4.0", PC, PW, requested_by="owner@example.invalid")) + "\n"
    )
    busy = {"request_id": "00000000-0000-4000-8000-000000000001", "action": "promote", "since": "x"}
    engine.paths.admin.mkdir()
    (engine.paths.admin / "busy.json").write_text(json.dumps(busy))
    snapshot = engine.snapshot()
    assert snapshot["releases"][0]["requested_by"] == "[redacted]"
    assert snapshot["busy"] == busy
    assert snapshot["rollback"]["available"] is False


# -- publishing -------------------------------------------------------------------


def test_publish_writes_status_atomically_with_fixed_modes(tmp_path: Path) -> None:
    engine, _, _, _ = setup(tmp_path)
    path = engine.publish_status()
    assert path == engine.paths.admin / "outbox" / "status.json"
    assert json.loads(path.read_text())["v"] == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    for directory in (engine.paths.admin, path.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    assert os.listdir(path.parent) == ["status.json"]


def test_publish_failure_keeps_the_previous_file_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, _, _ = setup(tmp_path)
    path = engine.publish_status()
    before = path.read_text()

    def broken(source, target):
        raise OSError("rename failed")

    monkeypatch.setattr(MODULE.os, "replace", broken)
    with pytest.raises(OSError, match="rename failed"):
        engine.publish_status()
    assert path.read_text() == before
    assert os.listdir(path.parent) == ["status.json"]


def test_publish_refuses_a_snapshot_over_256_kb(tmp_path: Path) -> None:
    engine, _, _, _ = setup(tmp_path)
    engine.snapshot = lambda **_: {"v": 1, "pad": "x" * MODULE.STATUS_MAX_BYTES}
    with pytest.raises(MODULE.ReleaseError, match="256 KB"):
        engine.publish_status()
    assert not (engine.paths.admin / "outbox" / "status.json").exists()


class QuietGitHub:
    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        return {"workflow_runs": [], "artifacts": []}


def test_tick_publishes_and_survives_a_publish_error(tmp_path: Path) -> None:
    engine, _, _, _ = setup(tmp_path)
    engine.github = QuietGitHub()
    assert engine.tick() == []
    published = engine.paths.admin / "outbox" / "status.json"
    assert json.loads(published.read_text())["environments"]["staging"]["core_sha"] == SC

    def fail(**_: Any) -> Path:
        raise OSError("disk full")

    engine.publish_status = fail
    assert engine.tick() == [{"status_publish_error": "disk full"}]


# -- dry-run promote ----------------------------------------------------------------


def test_dry_run_promote_rehearses_attempts_and_changes_nothing(tmp_path: Path) -> None:
    engine, _, _, _ = setup(tmp_path)
    engine.paths.releases.write_text(json.dumps(release("v0.4.0", PC, PW)) + "\n")
    ledger, history = engine.paths.releases.read_text(), engine.paths.history.read_text()
    attempts: list[tuple[str, bool, str]] = []

    def attempt(environment, component, build, *, dry_run, trigger):
        attempts.append((component, dry_run, build.sha))
        return {"component": component, "result": "dry-run"}

    engine.attempt = attempt
    result = engine.promote("minor", "v0.5.0", requested_by="cli:op", trigger="cli", dry_run=True)
    assert [entry["result"] for entry in result] == ["dry-run", "dry-run"]
    assert attempts == [("core", True, SC), ("web", True, SW)]
    assert engine.paths.releases.read_text() == ledger
    assert engine.paths.history.read_text() == history
    assert not (engine.paths.state / "train-inflight.json").exists()
    assert not list(engine.paths.state.glob("*.failed"))
    with pytest.raises(MODULE.ReleaseError, match="next version"):
        engine.promote("minor", "v0.4.1", requested_by="cli:op", trigger="cli", dry_run=True)


def test_dry_run_promote_skips_running_core_and_never_flags_a_failure(tmp_path: Path) -> None:
    engine, _, core, _ = setup(tmp_path)
    core["production"] = SC
    engine.deploy_web = lambda *args, **kwargs: (_ for _ in ()).throw(
        MODULE.ReleaseError("web rehearsal failed")
    )
    result = engine.promote("patch", "v0.4.1", requested_by="cli:op", trigger="cli", dry_run=True)
    assert [(entry["component"], entry["result"]) for entry in result] == [("web", "failed")]
    assert not engine.paths.failed_flag("production", "web").exists()
    assert not engine.is_paused("production")
    assert engine.production_releases()[0]["version"] == "v0.4.0"


# -- production pair rollback --------------------------------------------------------


def rollback_setup(tmp_path: Path):
    engine, runner, core, web = setup(tmp_path)
    calls: list[str] = []

    def rollback_core(environment, *, record_release=True):
        assert (environment, record_release) == ("production", False)
        calls.append("core")
        core["production"] = RC
        return {"restored_sha": RC, "result": "success"}

    def rollback_web(environment):
        calls.append("web")
        web["production"] = RW
        return {"restored_image": IMAGES[RW], "restored_sha": RW, "log": "x"}

    engine.rollback_core = rollback_core
    engine.rollback_web = rollback_web
    return engine, core, web, calls


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("disabled", "not enabled"),
        ("one_release", "there is no earlier production release"),
        ("current_is_rollback", "the current release is already a rollback"),
        ("other_pair", "production does not run v0.4.0"),
        ("build_missing", "the builds of v0.3.0 are no longer stored"),
        ("schema_changed", r"^Rollback not available: the database changed in v0\.4\.0\.$"),
        ("head_unknown", "database version of a release is unknown"),
        ("web_not_restorable", "the web release of v0.3.0 cannot be restored"),
        ("stale_sha", "production core changed since"),
        ("stale_version", "production version changed since"),
    ],
)
def test_rollback_refusals_change_nothing(tmp_path: Path, change: str, message: str) -> None:
    engine, core, web, calls = rollback_setup(tmp_path)
    kwargs: dict[str, Any] = {}
    if change == "disabled":
        engine.paths.production_enabled.unlink()
    elif change == "one_release":
        engine.paths.releases.write_text(json.dumps(release("v0.4.0", PC, PW)) + "\n")
    elif change == "current_is_rollback":
        engine.append_release(
            release("v0.3.0", RC, RW, action="rollback", rolled_back_from="v0.4.0")
        )
    elif change == "other_pair":
        web["production"] = SW
    elif change == "build_missing":
        (engine.paths.store / RW / "web.provenance.json").unlink()
    elif change in ("schema_changed", "head_unknown"):
        head = "20261001_0002" if change == "schema_changed" else "missing"
        manifest = engine.paths.application / "releases" / PC / "release-images.env"
        manifest.write_text(f"AC_MIGRATION_HEAD={head}\n")
    elif change == "web_not_restorable":
        engine.paths.history.write_text("")
    elif change == "stale_sha":
        kwargs["expected_sha"] = SC
    else:
        kwargs["expected_version"] = "v0.3.0"
    ledger = engine.paths.releases.read_text()
    with pytest.raises(MODULE.ReleaseError, match=message):
        engine.rollback_production(requested_by="cli:op", trigger="cli", **kwargs)
    assert calls == []
    assert engine.paths.releases.read_text() == ledger
    if change not in ("stale_sha", "stale_version"):
        with pytest.raises(MODULE.ReleaseError, match=message):
            engine.rollback_target()


def test_rollback_restores_core_then_web_and_records_one_release(tmp_path: Path) -> None:
    engine, _, _, calls = rollback_setup(tmp_path)
    steps = engine.rollback_production(
        requested_by="admin:person", trigger="admin", expected_sha=PC, expected_version="v0.4.0"
    )
    assert [(step["component"], step["result"]) for step in steps] == [
        ("core", "success"),
        ("web", "success"),
    ]
    assert calls == ["core", "web"]
    records = engine.release_records()
    assert len(records) == 3
    assert {key: records[-1][key] for key in ("version", "core_sha", "web_sha")} == {
        "version": "v0.3.0",
        "core_sha": RC,
        "web_sha": RW,
    }
    assert (records[-1]["action"], records[-1]["rolled_back_from"]) == ("rollback", "v0.4.0")
    assert records[-1]["requested_by"] == "admin:person"
    assert engine.history()[-1]["action"] == "rollback"
    assert engine.next_version("patch") == "v0.4.1"


def test_rollback_retry_after_failed_web_skips_the_core(tmp_path: Path) -> None:
    engine, core, _, calls = rollback_setup(tmp_path)
    core["production"] = RC
    steps = engine.rollback_production(requested_by="cli:op", trigger="cli")
    assert [step["result"] for step in steps] == ["skipped", "success"]
    assert calls == ["web"]
    assert engine.production_releases()[0]["action"] == "rollback"


def test_rollback_skips_the_web_when_the_target_web_already_runs(tmp_path: Path) -> None:
    engine, _, _, calls = rollback_setup(tmp_path)
    engine.paths.releases.write_text(
        "".join(
            json.dumps(r) + "\n" for r in (release("v0.3.0", RC, PW), release("v0.4.0", PC, PW))
        )
    )
    steps = engine.rollback_production(requested_by="cli:op", trigger="cli")
    assert [step["result"] for step in steps] == ["success", "skipped"]
    assert calls == ["core"]
    assert engine.production_releases()[0]["web_sha"] == PW


def test_restored_web_that_is_not_the_target_fails_without_a_record(tmp_path: Path) -> None:
    engine, _, web, calls = rollback_setup(tmp_path)

    def wrong_web(environment):
        calls.append("web")
        web["production"] = SW
        return {"restored_image": IMAGES[SW], "restored_sha": RW, "log": "x"}

    engine.rollback_web = wrong_web
    steps = engine.rollback_production(requested_by="cli:op", trigger="cli")
    assert [step["result"] for step in steps] == ["success", "failed"]
    assert "not the target release" in steps[-1]["error"]
    assert len(engine.release_records()) == 2
    assert engine.is_paused("production")
    assert engine.history()[-1]["result"] == "failed"


def test_dry_run_rollback_plans_steps_and_changes_nothing(tmp_path: Path) -> None:
    engine, _, _, calls = rollback_setup(tmp_path)
    ledger, history = engine.paths.releases.read_text(), engine.paths.history.read_text()
    steps = engine.rollback_production(requested_by="cli:op", trigger="cli", dry_run=True)
    assert steps == [
        {"component": "core", "result": "dry-run", "error": None},
        {"component": "web", "result": "dry-run", "error": None},
    ]
    assert calls == []
    assert engine.paths.releases.read_text() == ledger
    assert engine.paths.history.read_text() == history
    assert not engine.is_paused("production")


# -- CLI ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "outcome", "code"),
    [
        (["rollback", "staging"], None, 2),
        (["rollback", "production"], "refuse", 2),
        (["rollback", "production"], "failed", 1),
        (["rollback", "production", "--dry-run"], "dry-run", 0),
        (["rollback", "staging", "--component", "web", "--dry-run"], None, 2),
    ],
)
def test_rollback_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], outcome: str | None, code: int
) -> None:
    seen: list[dict[str, Any]] = []

    def rollback_production(self, **kwargs):
        seen.append(kwargs)
        if outcome == "refuse":
            raise MODULE.ReleaseError("Rollback not available: the database changed in v0.4.0.")
        return [{"component": "core", "result": outcome, "error": None}]

    monkeypatch.setattr(MODULE.Engine, "rollback_production", rollback_production)
    monkeypatch.setenv("SUDO_USER", "operator")
    assert MODULE.main(argv) == code
    if outcome:
        assert seen == [
            {"requested_by": "cli:operator", "trigger": "cli", "dry_run": "--dry-run" in argv}
        ]
    else:
        assert seen == []


def test_promote_dry_run_and_publish_status_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[dict[str, Any]] = []

    def promote(self, bump, version, **kwargs):
        seen.append({"bump": bump, "version": version, **kwargs})
        return [{"component": "web", "result": "dry-run"}]

    monkeypatch.setattr(MODULE.Engine, "promote", promote)
    monkeypatch.setattr(MODULE.Engine, "publish_status", lambda self: Path("/x/status.json"))
    monkeypatch.setenv("SUDO_USER", "operator")
    assert MODULE.main(["promote", "--bump", "minor", "--version", "v0.5.0", "--dry-run"]) == 0
    assert seen == [
        {
            "bump": "minor",
            "version": "v0.5.0",
            "requested_by": "cli:operator",
            "trigger": "cli",
            "dry_run": True,
        }
    ]
    assert MODULE.main(["publish-status"]) == 0
    assert capsys.readouterr().out.endswith("/x/status.json\n")

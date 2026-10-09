"""Exact edge projection recovery on a fictional, secret-free filesystem."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ac_release_edge_tests", Path(__file__).resolve().parents[2] / "infra/release/ac_release.py"
)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
OWNER = M.EDGE_REPAIR_OWNER


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(path: Path, raw: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(mode)


def filesystem(root: Path) -> dict:
    result = {}
    for p in root.rglob("*"):
        info = p.lstat()
        result[str(p.relative_to(root))] = (
            info.st_mode,
            info.st_uid,
            info.st_gid,
            None if p.is_dir() else M.EdgeProjectionRecovery.metadata(info),
            os.readlink(p) if p.is_symlink() else None if p.is_dir() else p.read_bytes(),
        )
    return result


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "EDGE_REPAIR_UID", os.geteuid())
    monkeypatch.setattr(M, "EDGE_REPAIR_GID", os.getegid())
    monkeypatch.setattr(M, "EDGE_REPAIR_ANCHOR", tmp_path)
    paths = M.Paths(
        application=tmp_path / "application",
        state=tmp_path / "state",
        config=tmp_path / "config",
        sales_xray=tmp_path / "sales-xray",
        lock=tmp_path / "release.lock",
    )
    for directory in (paths.application, paths.state, paths.config):
        directory.mkdir()
    write(paths.lock, b"", 0o600)
    write(paths.application / ".deployment.lock", b"", 0o600)
    owner = paths.application / "releases" / OWNER
    projection = paths.application / "edge-route-releases" / OWNER
    hashes = {}
    for env in M.ENVIRONMENTS:
        raw = f"{env} immutable route\n".encode()
        drift = raw + b"# the exact recorded cache addition\n"
        write(owner / "edge-routes" / f"{env}.caddy", raw)
        write(owner / "edge-routes" / f"{env}-hold.caddy", b"hold\n")
        write(projection / f"{env}.caddy", drift)
        write(projection / f"{env}-hold.caddy", b"hold\n")
        hashes[env] = (sha(drift), sha(raw))
        selectors = paths.application / "edge-routes"
        selectors.mkdir(exist_ok=True)
        (selectors / f"{env}.caddy").symlink_to(projection / f"{env}.caddy")
        (paths.application / f"current-{env}").symlink_to(owner)
        activation = {
            "release_id": OWNER,
            "environment": env,
            "native_image_ref": "sha256:" + "d" * 64,
            "helper_unit": f"native-{env}.service",
        }
        for key, digest_key in (
            ("compose_env_file", "compose_env_sha256"),
            ("service_config_file", "service_config_sha256"),
            ("approval_file", "approval_sha256"),
        ):
            p = paths.sales_xray / env / key
            raw = b"fictional binding, contains no credentials\n"
            write(p, raw)
            activation[key] = str(p)
            activation[digest_key] = sha(raw)
        write(paths.sales_xray / env / f"activation-{OWNER}.json", json.dumps(activation).encode())
    write(owner / "RELEASE-COMMIT", (OWNER + "\n").encode())
    write(
        owner / "release-images.env",
        b"".join((key + "=fixture\n").encode() for key in M.CORE_IMAGE_KEYS),
    )
    entries = sorted(p for p in owner.rglob("*") if p.is_file())
    manifest = "".join(f"{sha(p.read_bytes())}  {p.relative_to(owner)}\n" for p in entries).encode()
    write(owner / "RELEASE-FILES.sha256", manifest)
    monkeypatch.setattr(M, "EDGE_REPAIR_MANIFEST", sha(manifest))
    monkeypatch.setattr(M, "EDGE_REPAIR_COUNT", len(entries))
    monkeypatch.setattr(M, "EDGE_REPAIR_HASHES", hashes)
    native = paths.application / "artifacts" / "native-image.json"
    write(native, b'{"fixture":true}\n')
    write(paths.state / "staging.paused", b"retained pause\n", 0o600)
    write(paths.state / "staging-core.failed", ("b" * 40 + "\n").encode(), 0o600)
    write(paths.config / "production.HELD-AUT-test", b"retained hold\n", 0o600)
    write(paths.state / "history.jsonl", b"original history\n", 0o600)
    write(paths.state / "releases.jsonl", b"original release history\n", 0o600)
    for directory in tmp_path.rglob("*"):
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o755)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            out = json.dumps(
                {
                    "id": argv[-1],
                    "image": "sha256:" + "c" * 64,
                    "configured_image": "fixture",
                    "status": "running",
                    "started": "fixed",
                    "restarts": 0,
                    "mounts": [],
                }
            )
        elif argv[:2] == ["systemctl", "show"]:
            out = "ActiveState=active\nInvocationID=fixed\n"
        else:
            raise AssertionError(f"unexpected mutation or external call: {argv}")
        return subprocess.CompletedProcess(argv, 0, out, "")

    engine = M.Engine(paths=paths, run=run)
    monkeypatch.setattr(engine, "native_for_image", lambda image: ("a" * 40, native))
    repair = M.EdgeProjectionRecovery(engine)
    repair.calls = calls
    return repair


def rehearse(recovery):
    return recovery.execute(OWNER)["plan_sha256"]


def test_rehearsal_is_deterministic_and_mutation_free(recovery):
    before = filesystem(M.EDGE_REPAIR_ANCHOR)
    first = recovery.execute(OWNER)
    second = recovery.execute(OWNER)
    assert first == second
    assert first["result"] == "dry-run"
    assert set(first["plan"]["files"]) == set(M.ENVIRONMENTS)
    assert not recovery.receipts.exists()
    assert filesystem(M.EDGE_REPAIR_ANCHOR) == before
    assert all("Config.Env" not in " ".join(call) for call in recovery.calls)


def test_apply_preserves_audit_bindings_and_is_idempotent(recovery):
    original = recovery.plan()
    before = {env: recovery.projection(env)[0] for env in M.ENVIRONMENTS}
    digest = rehearse(recovery)
    result = recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert result["result"] == "applied"
    receipt = Path(result["receipt"])
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o555
    for env in M.ENVIRONMENTS:
        assert recovery.projection(env)[1]["sha256"] == M.EDGE_REPAIR_HASHES[env][1]
        assert (receipt / f"{env}.before").read_bytes() == before[env]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o444 for p in receipt.iterdir())
    recovery.preserved(original)
    before_repeat = filesystem(M.EDGE_REPAIR_ANCHOR)
    assert recovery.execute(OWNER, apply=True, plan_sha256=digest)["result"] == "already-applied"
    assert filesystem(M.EDGE_REPAIR_ANCHOR) == before_repeat


@pytest.mark.parametrize("mode", ["apply", "rollback"])
@pytest.mark.parametrize("digest", [None, "", "../outside", "a" * 63])
def test_requires_explicit_plan_digest(recovery, mode, digest):
    with pytest.raises(M.ReleaseError, match="reviewed plan digest"):
        recovery.execute(OWNER, **{mode: True}, plan_sha256=digest)
    assert not recovery.receipts.exists()


def test_changed_owner_is_rejected(recovery):
    with pytest.raises(M.ReleaseError, match="exact reviewed owner"):
        recovery.execute("b" * 40)


@pytest.mark.parametrize("kind", ["hold", "core", "escape", "relative"])
def test_changed_selectors_are_rejected(recovery, kind):
    if kind == "core":
        selector = recovery.paths.application / "current-staging"
        target = recovery.paths.application / "releases" / ("b" * 40)
    else:
        selector = recovery.paths.application / "edge-routes" / "staging.caddy"
        target = {
            "hold": recovery.projections / "staging-hold.caddy",
            "escape": M.EDGE_REPAIR_ANCHOR / "outside.caddy",
            "relative": Path("../edge-route-releases") / OWNER / "staging.caddy",
        }[kind]
    selector.unlink()
    selector.symlink_to(target)
    with pytest.raises(M.ReleaseError, match="selectors changed"):
        rehearse(recovery)


@pytest.mark.parametrize("kind", ["unexpected-drift", "metadata", "symlink", "hardlink", "parent"])
def test_rejects_unsafe_projection_inputs(recovery, kind):
    path = recovery.projections / "staging.caddy"
    if kind == "unexpected-drift":
        write(path, b"unknown drift\n")
    elif kind == "metadata":
        path.chmod(0o644)
    elif kind == "symlink":
        path.unlink()
        path.symlink_to(recovery.owner / "edge-routes/staging.caddy")
    elif kind == "hardlink":
        os.link(path, M.EDGE_REPAIR_ANCHOR / "alias")
    else:
        recovery.projections.chmod(0o775)
    with pytest.raises((M.ReleaseError, OSError)):
        rehearse(recovery)
    assert not recovery.receipts.exists()


def test_full_manifest_is_verified(recovery):
    write(recovery.owner / "release-images.env", b"different immutable owner\n")
    with pytest.raises(M.ReleaseError, match="full manifest verification"):
        rehearse(recovery)


@pytest.mark.parametrize("line", [b"../outside", b"/absolute", b"edge-routes/../staging.caddy"])
def test_manifest_path_escapes_rejected_even_with_pinned_manifest(recovery, monkeypatch, line):
    raw = b"a" * 64 + b"  " + line + b"\n"
    write(recovery.owner / "RELEASE-FILES.sha256", raw)
    monkeypatch.setattr(M, "EDGE_REPAIR_MANIFEST", sha(raw))
    with pytest.raises(M.ReleaseError, match="unsafe path"):
        rehearse(recovery)


@pytest.mark.parametrize("lock", ["release", "deployment"])
def test_busy_lock_is_rejected_without_mutation(recovery, lock):
    path = (
        recovery.paths.lock
        if lock == "release"
        else recovery.paths.application / ".deployment.lock"
    )
    before = filesystem(M.EDGE_REPAIR_ANCHOR)
    with path.open("rb") as handle:
        M.fcntl.flock(handle, M.fcntl.LOCK_EX | M.fcntl.LOCK_NB)
        with pytest.raises(M.ReleaseError, match="lock is busy"):
            rehearse(recovery)
    assert filesystem(M.EDGE_REPAIR_ANCHOR) == before


def test_missing_lock_is_not_created(recovery):
    recovery.paths.lock.unlink()
    with pytest.raises(FileNotFoundError):
        rehearse(recovery)
    assert not recovery.paths.lock.exists()


def test_changed_containment_invalidates_reviewed_plan(recovery):
    digest = rehearse(recovery)
    write(recovery.paths.state / "staging.paused", b"different pause\n", 0o600)
    with pytest.raises(M.ReleaseError, match="plan changed since review"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert not recovery.receipts.exists()


def test_changed_runtime_identity_invalidates_reviewed_plan(recovery, monkeypatch):
    digest = rehearse(recovery)
    original = recovery.container
    monkeypatch.setattr(recovery, "container", lambda name: {**original(name), "image": "changed"})
    with pytest.raises(M.ReleaseError, match="plan changed since review"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert not recovery.receipts.exists()


def test_fault_after_first_atomic_write_compensates_and_preserves_receipt(recovery, monkeypatch):
    digest = rehearse(recovery)
    original = recovery.replace
    fail = True

    def interrupted(env, raw, expected, digest, **kwargs):
        nonlocal fail
        original(env, raw, expected, digest, **kwargs)
        if fail:
            fail = False
            raise RuntimeError("fictional interruption")

    monkeypatch.setattr(recovery, "replace", interrupted)
    with pytest.raises(M.ReleaseError, match="retained receipt"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    for env in M.ENVIRONMENTS:
        assert recovery.projection(env)[1]["sha256"] == M.EDGE_REPAIR_HASHES[env][0]
    assert (recovery.receipts / digest / "failure.json").exists()
    assert not (recovery.receipts / digest / "completed.json").exists()
    with pytest.raises(M.ReleaseError, match="interrupted receipt"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert recovery.execute(OWNER, rollback=True, plan_sha256=digest)["result"] == "rolled-back"


def test_explicit_rollback_preserves_original_receipt_and_is_idempotent(recovery):
    digest = rehearse(recovery)
    recovery.execute(OWNER, apply=True, plan_sha256=digest)
    receipt = recovery.receipts / digest
    original = {p.name: p.read_bytes() for p in receipt.iterdir()}
    assert recovery.execute(OWNER, rollback=True, plan_sha256=digest)["result"] == "rolled-back"
    assert {p.name: p.read_bytes() for p in receipt.iterdir()} == original
    for env in M.ENVIRONMENTS:
        assert recovery.projection(env)[1]["sha256"] == M.EDGE_REPAIR_HASHES[env][0]
    before_repeat = filesystem(M.EDGE_REPAIR_ANCHOR)
    assert (
        recovery.execute(OWNER, rollback=True, plan_sha256=digest)["result"]
        == "already-rolled-back"
    )
    assert filesystem(M.EDGE_REPAIR_ANCHOR) == before_repeat


def test_incomplete_backup_refuses_apply_and_rollback(recovery):
    digest = rehearse(recovery)
    recovery.execute(OWNER, apply=True, plan_sha256=digest)
    directory = recovery.receipts / digest
    directory.chmod(0o700)
    (directory / "staging.before").unlink()
    for mode in ("apply", "rollback"):
        with pytest.raises(M.ReleaseError, match="incomplete"):
            recovery.execute(OWNER, **{mode: True}, plan_sha256=digest)


def test_cli_routes_without_loading_github_or_running_installer(recovery, monkeypatch, capsys):
    monkeypatch.setattr(M, "Paths", lambda: recovery.paths)
    monkeypatch.setattr(M, "Engine", lambda **kwargs: recovery.engine)
    assert M.main(["recover-edge-projections", "--owner-release", OWNER, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "dry-run"
    assert not recovery.receipts.exists()


@pytest.mark.parametrize("phase", ["stage", "rename"])
def test_process_death_can_be_compensated_by_supported_rollback(recovery, phase):
    digest = rehearse(recovery)
    child = os.fork()
    if child == 0:
        if phase == "stage":
            original = recovery.save

            def save(path, raw):
                original(path, raw)
                if path.name.startswith(".edge-repair-"):
                    os._exit(73)

            recovery.save = save
        else:
            original = recovery.replace

            def replace(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(73)

            recovery.replace = replace
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
        os._exit(74)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 73
    with pytest.raises(M.ReleaseError, match="interrupted receipt"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    result = recovery.execute(OWNER, rollback=True, plan_sha256=digest)
    assert result["result"] == "rolled-back"
    for env in M.ENVIRONMENTS:
        assert recovery.projection(env)[1]["sha256"] == M.EDGE_REPAIR_HASHES[env][0]
    assert (
        recovery.execute(OWNER, rollback=True, plan_sha256=digest)["result"]
        == "already-rolled-back"
    )


def test_interrupted_rollback_resumes_without_overwriting_history(recovery, monkeypatch):
    digest = rehearse(recovery)
    recovery.execute(OWNER, apply=True, plan_sha256=digest)
    original = recovery.replace
    fail = True

    def interrupted(*args, **kwargs):
        nonlocal fail
        original(*args, **kwargs)
        if fail:
            fail = False
            raise RuntimeError("fictional rollback interruption")

    monkeypatch.setattr(recovery, "replace", interrupted)
    with pytest.raises(RuntimeError):
        recovery.execute(OWNER, rollback=True, plan_sha256=digest)
    receipt = recovery.receipts / (digest + "-rollback")
    prepared = (receipt / "prepared.json").read_bytes()
    assert recovery.execute(OWNER, rollback=True, plan_sha256=digest)["result"] == "rolled-back"
    assert (receipt / "prepared.json").read_bytes() == prepared


def test_changed_bindings_during_audit_preparation_prevent_first_write(recovery, monkeypatch):
    digest = rehearse(recovery)
    original = recovery.save
    before = {env: recovery.projection(env)[0] for env in M.ENVIRONMENTS}

    def concurrent(path, raw):
        original(path, raw)
        if path.name == "prepared.json":
            write(recovery.paths.state / "history.jsonl", b"concurrent event\n", 0o600)

    monkeypatch.setattr(recovery, "save", concurrent)
    with pytest.raises(M.ReleaseError, match="retained receipt"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert {env: recovery.projection(env)[0] for env in M.ENVIRONMENTS} == before


def test_replacement_race_preserves_unknown_drift(recovery, monkeypatch):
    digest = rehearse(recovery)
    original = recovery.save

    def concurrent(path, raw):
        original(path, raw)
        if path.name == ".edge-repair-" + digest + "-staging":
            write(recovery.projections / "staging.caddy", b"unexpected concurrent route\n")

    monkeypatch.setattr(recovery, "save", concurrent)
    with pytest.raises(M.ReleaseError, match="unexpected drift"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert recovery.projection("staging")[0] == b"unexpected concurrent route\n"
    assert (recovery.receipts / digest / "prepared.json").exists()


@pytest.mark.parametrize("mode", ["apply", "rollback"])
@pytest.mark.parametrize(
    ("phase", "drift_env"),
    [
        ("first-replacement", "staging"),
        ("last-replacement", "staging"),
        ("before-completion", "staging"),
        ("before-completion", "production"),
    ],
)
def test_final_projection_drift_refuses_completion_and_preserves_evidence(
    recovery, monkeypatch, mode, phase, drift_env
):
    digest = rehearse(recovery)
    if mode == "rollback":
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    original_receipt = recovery.receipts / digest
    original_evidence = (
        {p.name: p.read_bytes() for p in original_receipt.iterdir()}
        if original_receipt.exists()
        else None
    )
    original_replace = recovery.replace
    original_preserved = recovery.preserved
    injected = False
    unknown = b"unknown concurrent public route\n"
    target_index = 1 if mode == "apply" else 0

    def inject():
        nonlocal injected
        if not injected:
            injected = True
            write(recovery.projections / f"{drift_env}.caddy", unknown)

    def replace(env, *args, **kwargs):
        original_replace(env, *args, **kwargs)
        if (phase == "first-replacement" and env == M.ENVIRONMENTS[0]) or (
            phase == "last-replacement" and env == M.ENVIRONMENTS[-1]
        ):
            inject()

    def preserved(plan):
        original_preserved(plan)
        if phase == "before-completion" and all(
            recovery.projection(env)[1]["sha256"] == M.EDGE_REPAIR_HASHES[env][target_index]
            for env in M.ENVIRONMENTS
        ):
            inject()

    monkeypatch.setattr(recovery, "replace", replace)
    monkeypatch.setattr(recovery, "preserved", preserved)
    with pytest.raises(M.ReleaseError, match="unexpected drift|final projection"):
        recovery.execute(OWNER, **{mode: True}, plan_sha256=digest)
    assert injected
    assert recovery.projection(drift_env)[0] == unknown
    failed_receipt = recovery.receipts / (digest + "-rollback" if mode == "rollback" else digest)
    assert (failed_receipt / "prepared.json").exists()
    assert not (failed_receipt / "completed.json").exists()
    for env in M.ENVIRONMENTS:
        assert (
            sha((original_receipt / f"{env}.before").read_bytes()) == M.EDGE_REPAIR_HASHES[env][0]
        )
    if original_evidence is not None:
        assert {p.name: p.read_bytes() for p in original_receipt.iterdir()} == original_evidence
    recovery.preserved(json.loads((original_receipt / "plan.json").read_bytes()))
    before_retry = filesystem(M.EDGE_REPAIR_ANCHOR)
    with pytest.raises(M.ReleaseError, match="unexpected drift"):
        recovery.execute(OWNER, rollback=True, plan_sha256=digest)
    assert filesystem(M.EDGE_REPAIR_ANCHOR) == before_retry


def test_broken_hold_symlink_is_rejected(recovery):
    (recovery.paths.config / "production.HELD-broken").symlink_to("missing")
    with pytest.raises(OSError):
        rehearse(recovery)


def test_core_image_mismatch_prevents_rehearsal(recovery, monkeypatch):
    original = recovery.container
    monkeypatch.setattr(
        recovery, "container", lambda name: {**original(name), "configured_image": "wrong"}
    )
    with pytest.raises(M.ReleaseError, match="installed core differs"):
        rehearse(recovery)


def test_prior_plan_refuses_advanced_live_core_before_audit_creation(recovery):
    digest = rehearse(recovery)
    selector = recovery.paths.application / "current-production"
    selector.unlink()
    selector.symlink_to(recovery.paths.application / "releases" / ("d" * 40))
    before = filesystem(M.EDGE_REPAIR_ANCHOR)
    with pytest.raises(M.ReleaseError, match="selectors changed"):
        recovery.execute(OWNER, apply=True, plan_sha256=digest)
    assert filesystem(M.EDGE_REPAIR_ANCHOR) == before


def test_repeat_apply_and_rollback_refuse_new_drift(recovery):
    digest = rehearse(recovery)
    recovery.execute(OWNER, apply=True, plan_sha256=digest)
    write(recovery.projections / "staging.caddy", b"new drift\n")
    for mode in ("apply", "rollback"):
        with pytest.raises(M.ReleaseError, match="changed|unexpected drift"):
            recovery.execute(OWNER, **{mode: True}, plan_sha256=digest)

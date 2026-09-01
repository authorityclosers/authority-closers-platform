from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" and os.geteuid() != 0,
    reason="the root-owned restore boundary is exercised by the root control-plane gate",
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "vps-foundation" / "scripts" / "ac-restic-postgres-restore-proof.py"
RESTORE_DRILL_SCRIPT = ROOT / "infra" / "application" / "scripts" / "restore-drill.py"
FOUNDATION = ROOT / "infra" / "vps-foundation"
MIGRATION_HEAD_FIXTURE = "20000101_0001"

spec = importlib.util.spec_from_file_location("ac_restic_postgres_restore_proof", SCRIPT)
assert spec and spec.loader
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)

drill_spec = importlib.util.spec_from_file_location(
    "ac_application_restore_drill_contract", RESTORE_DRILL_SCRIPT
)
assert drill_spec and drill_spec.loader
restore_drill_contract = importlib.util.module_from_spec(drill_spec)
sys.modules[drill_spec.name] = restore_drill_contract
drill_spec.loader.exec_module(restore_drill_contract)


def _snapshot(
    now: dt.datetime, *, snapshot_id: str = "a" * 64, tags: list[str] | None = None
) -> str:
    return json.dumps(
        [
            {
                "id": snapshot_id,
                "time": (now - dt.timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
                "tags": tags or [proof.RESTIC_TAG, "environment=staging"],
            }
        ]
    )


def _tree(
    environment: str = "staging",
    capture: str = "20260830T120000.000000Z-123-staging",
    snapshot_id: str = "a" * 64,
) -> str:
    prefix = f"/srv/authority-closers/backups/application/{environment}/logical/{capture}"
    return "\n".join(
        (
            json.dumps({"struct_type": "snapshot", "id": snapshot_id}),
            json.dumps({"struct_type": "node", "type": "dir", "path": "/srv"}),
            json.dumps({"struct_type": "node", "type": "file", "path": f"{prefix}/backup.dump"}),
            json.dumps({"struct_type": "node", "type": "file", "path": f"{prefix}/metadata.json"}),
        )
    )


def _write_pair(directory: Path, environment: str = "staging") -> tuple[Path, Path]:
    relative = Path(
        "srv",
        "authority-closers",
        "backups",
        "application",
        environment,
        "logical",
        "20260830T120000.000000Z-123-" + environment,
    )
    pair_dir = directory / relative
    pair_dir.mkdir(parents=True)
    dump = pair_dir / "backup.dump"
    dump.write_bytes(b"PGDMP" + b"fixture")
    captured = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=30)
    payload = {
        "artifact_type": "authority-closers-postgresql-logical",
        "restic_tag": proof.RESTIC_TAG,
        "environment": environment,
        "release_id": "a" * 40,
        "compose_project": f"ac-application-{environment}",
        "database_role": "ac_backup",
        "format": "custom",
        "verification": "pg_restore --list",
        "capture_started_at": (captured - dt.timedelta(seconds=1)).isoformat(),
        "capture_completed_at": captured.isoformat(),
        "captured_at": captured.isoformat(),
        "captured_at_epoch_ns": int(captured.timestamp() * 1_000_000_000),
        "capture_clock": "CLOCK_REALTIME",
        "dump_bytes": dump.stat().st_size,
        "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "row_counts": {table: 0 for table in proof.PARITY_TABLES},
    }
    metadata = pair_dir / "metadata.json"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    return dump, metadata


def _write_release(root: Path, environment: str = "staging") -> Path:
    release = root / "srv" / "authority-closers" / "application" / "releases" / ("a" * 40)
    (release / "scripts").mkdir(parents=True)
    (release / "scripts" / "restore-drill.py").write_text("# immutable drill\n", encoding="utf-8")
    (release / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    values = {
        "AC_ADMIN_IMAGE": "sha256:" + "b" * 64,
        "AC_ADMIN_REGISTRY_DIGEST": (
            "ghcr.io/authorityclosers/authority-closers-admin-web@sha256:" + "b" * 64
        ),
        "AC_ADMIN_TRANSPORT_DIGEST": "sha256:" + "b" * 64,
        "AC_API_IMAGE": "sha256:" + "c" * 64,
        "AC_API_REGISTRY_DIGEST": (
            "ghcr.io/authorityclosers/authority-closers-api@sha256:" + "c" * 64
        ),
        "AC_API_TRANSPORT_DIGEST": "sha256:" + "c" * 64,
        "AC_LEARNER_IMAGE": "sha256:" + "d" * 64,
        "AC_LEARNER_REGISTRY_DIGEST": (
            "ghcr.io/authorityclosers/authority-closers-learner-web@sha256:" + "d" * 64
        ),
        "AC_LEARNER_TRANSPORT_DIGEST": "sha256:" + "d" * 64,
        "AC_MIGRATION_HEAD": MIGRATION_HEAD_FIXTURE,
        "AC_RELEASE_ID": "a" * 40,
    }
    (release / "release-images.env").write_text(
        "\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n",
        encoding="utf-8",
    )
    files = sorted(path for path in release.rglob("*") if path.is_file())
    (release / "RELEASE-FILES.sha256").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"./{path.relative_to(release).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )
    current = root / "srv" / "authority-closers" / "application" / f"current-{environment}"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(release, target_is_directory=True)
    return release


def test_select_latest_requires_one_unambiguous_fresh_snapshot() -> None:
    now = dt.datetime.now(dt.UTC)
    older = {
        "id": "b" * 64,
        "time": (now - dt.timedelta(seconds=90)).isoformat(),
        "tags": [proof.RESTIC_TAG, "environment=staging"],
    }
    latest = {
        "id": "a" * 64,
        "time": (now - dt.timedelta(seconds=30)).isoformat(),
        "tags": [proof.RESTIC_TAG, "environment=staging", "host=backup"],
    }
    selected = proof.select_latest_snapshot(json.dumps([older, latest]), "staging", now=now)
    assert selected.snapshot_id == "a" * 64

    tie = dict(latest, id="c" * 64)
    with pytest.raises(proof.RestoreProofError, match="ambiguous"):
        proof.select_latest_snapshot(json.dumps([latest, tie]), "staging", now=now)
    with pytest.raises(proof.RestoreProofError, match="stale"):
        proof.select_latest_snapshot(
            json.dumps([dict(latest, time=(now - dt.timedelta(minutes=16)).isoformat())]),
            "staging",
            now=now,
        )
    with pytest.raises(proof.RestoreProofError, match="ambiguous"):
        proof.select_latest_snapshot(
            json.dumps(
                [dict(latest, tags=[proof.RESTIC_TAG, proof.RESTIC_TAG, "environment=staging"])]
            ),
            "staging",
            now=now,
        )


def test_current_release_requires_root_owned_manifest_and_exact_local_images(
    tmp_path: Path,
) -> None:
    release = _write_release(tmp_path)
    selected = proof.resolve_current_release("staging", root=tmp_path)
    assert selected.release_dir == release
    assert selected.api_image == "sha256:" + "c" * 64

    selected.restore_drill.unlink()
    with pytest.raises(proof.RestoreProofError, match="checksum"):
        proof.resolve_current_release("staging", root=tmp_path)


@pytest.mark.parametrize(
    ("key", "unsafe_value", "message"),
    (
        ("AC_API_IMAGE", "sha256:" + "c" * 64 + "/layer", "image identity"),
        (
            "AC_API_REGISTRY_DIGEST",
            "ghcr.io/authorityclosers/authority-closers-api@sha256:" + "c" * 64 + "?tag=x",
            "registry provenance",
        ),
        ("AC_API_TRANSPORT_DIGEST", "sha256:" + "c" * 64 + ":tag", "transport identity"),
        ("AC_MIGRATION_HEAD", f"{MIGRATION_HEAD_FIXTURE};echo", "migration identity"),
        ("AC_RELEASE_ID", "a" * 40 + "../", "release identity"),
    ),
)
def test_release_manifest_values_use_key_specific_fail_closed_grammars(
    tmp_path: Path,
    key: str,
    unsafe_value: str,
    message: str,
) -> None:
    release = _write_release(tmp_path)
    manifest = release / "release-images.env"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    replacements = [
        f"{key}={unsafe_value}" if line.startswith(f"{key}=") else line for line in lines
    ]
    manifest.write_text("\n".join(replacements) + "\n", encoding="utf-8")

    with pytest.raises(proof.RestoreProofError, match=message):
        proof._parse_release_env(manifest)


def test_release_manifest_requires_each_local_image_to_match_its_transport_digest(
    tmp_path: Path,
) -> None:
    release = _write_release(tmp_path)
    manifest = release / "release-images.env"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text(
        "\n".join(
            "AC_API_TRANSPORT_DIGEST=sha256:" + "e" * 64
            if line.startswith("AC_API_TRANSPORT_DIGEST=")
            else line
            for line in lines
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(proof.RestoreProofError, match="transport identity is inconsistent"):
        proof._parse_release_env(manifest)


def test_snapshot_pair_rejects_extra_files_symlinks_and_multiple_captures() -> None:
    valid = _tree()
    pair = proof.select_snapshot_pair(valid, "staging", "a" * 64)
    assert pair.dump_path.endswith("/backup.dump")
    assert pair.metadata_path.endswith("/metadata.json")

    extra = (
        valid
        + "\n"
        + json.dumps({"struct_type": "node", "type": "file", "path": "/srv/unexpected.txt"})
    )
    with pytest.raises(proof.RestoreProofError, match="unexpected file path"):
        proof.select_snapshot_pair(extra, "staging", "a" * 64)
    extra_directory = (
        valid
        + "\n"
        + json.dumps(
            {
                "struct_type": "node",
                "type": "dir",
                "path": "/srv/authority-closers/unexpected",
            }
        )
    )
    with pytest.raises(proof.RestoreProofError, match="unexpected directory"):
        proof.select_snapshot_pair(extra_directory, "staging", "a" * 64)
    symlink = valid.replace('"type": "dir"', '"type": "symlink"')
    with pytest.raises(proof.RestoreProofError, match="non-regular"):
        proof.select_snapshot_pair(symlink, "staging", "a" * 64)
    other_prefix = (
        "/srv/authority-closers/backups/application/staging/logical/"
        "20260830T120001.000000Z-124-staging"
    )
    multiple = (
        valid
        + "\n"
        + "\n".join(
            (
                json.dumps(
                    {
                        "struct_type": "node",
                        "type": "file",
                        "path": f"{other_prefix}/backup.dump",
                    }
                ),
                json.dumps(
                    {
                        "struct_type": "node",
                        "type": "file",
                        "path": f"{other_prefix}/metadata.json",
                    }
                ),
            )
        )
    )
    with pytest.raises(proof.RestoreProofError, match="multiple captures"):
        proof.select_snapshot_pair(multiple, "staging", "a" * 64)

    with pytest.raises(proof.RestoreProofError, match="binding is inconsistent"):
        proof.select_snapshot_pair(_tree(snapshot_id="b" * 64), "staging", "a" * 64)
    with pytest.raises(proof.RestoreProofError, match="lacks an exact snapshot header"):
        proof.select_snapshot_pair("\n".join(valid.splitlines()[1:]), "staging", "a" * 64)


def test_metadata_verification_is_exact_and_digest_bound(tmp_path: Path) -> None:
    dump, metadata = _write_pair(tmp_path)
    release_id, captured_at, row_counts = proof._validate_metadata(metadata, dump, "staging")
    assert release_id == "a" * 40
    assert captured_at.tzinfo is not None
    assert set(row_counts) == set(proof.PARITY_TABLES)

    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["dump_sha256"] = "0" * 64
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="digest"):
        proof._validate_metadata(metadata, dump, "staging")

    payload["dump_sha256"] = hashlib.sha256(dump.read_bytes()).hexdigest()
    payload["unexpected"] = "unsafe"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="unexpected contract"):
        proof._validate_metadata(metadata, dump, "staging")


def test_capture_and_restic_timestamps_are_fresh_and_ordered(tmp_path: Path) -> None:
    dump, metadata = _write_pair(tmp_path)
    _release_id, captured_at, _row_counts = proof._validate_metadata(metadata, dump, "staging")
    with pytest.raises(proof.RestoreProofError, match="timestamps"):
        proof._validate_metadata(
            metadata,
            dump,
            "staging",
            now=captured_at + dt.timedelta(minutes=16),
        )

    now = dt.datetime.now(dt.UTC)
    snapshot = proof.Snapshot("a" * 64, now - dt.timedelta(seconds=30))
    proof.validate_snapshot_capture_timing(snapshot, now - dt.timedelta(minutes=1), now=now)
    with pytest.raises(proof.RestoreProofError, match="stale or inconsistent"):
        proof.validate_snapshot_capture_timing(
            proof.Snapshot("a" * 64, now - dt.timedelta(minutes=3)),
            now - dt.timedelta(seconds=30),
            now=now,
        )
    with pytest.raises(proof.RestoreProofError, match="stale or inconsistent"):
        proof.validate_snapshot_capture_timing(
            proof.Snapshot("a" * 64, now + dt.timedelta(minutes=7)),
            now - dt.timedelta(seconds=30),
            now=now,
        )


def test_restore_tree_requires_exact_root_owned_pair_and_cleanup_is_bounded(tmp_path: Path) -> None:
    restore_root = tmp_path / "restore-root"
    restore_dir = proof.create_restore_directory(restore_root)
    pair = proof.select_snapshot_pair(_tree(), "staging", "a" * 64)
    dump, metadata = _write_pair(restore_dir)
    assert proof._verify_restored_pair(restore_dir, pair) == (dump, metadata)
    stable_dir, stable_dump, stable_metadata = proof.copy_stable_pair(dump, metadata, restore_root)
    assert stable_dump.read_bytes() == dump.read_bytes()
    assert stable_metadata.read_bytes() == metadata.read_bytes()
    proof.remove_restore_directory(stable_dir, restore_root)
    proof.remove_restore_directory(restore_dir, restore_root)
    assert not restore_dir.exists()

    unsafe = proof.create_restore_directory(restore_root)
    (unsafe / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(proof.RestoreProofError, match="unsafe entry"):
        proof.remove_restore_directory(unsafe, restore_root)


def test_stable_pair_satisfies_the_real_restore_drill_metadata_contract(tmp_path: Path) -> None:
    restore_root = tmp_path / "restore-root"
    restored_dir = proof.create_restore_directory(restore_root)
    restored_dump, restored_metadata = _write_pair(restored_dir)
    stable_dir, stable_dump, stable_metadata = proof.copy_stable_pair(
        restored_dump, restored_metadata, restore_root
    )
    try:
        validated_metadata, _captured_at, release_id, dump_sha256, metadata_sha256 = (
            restore_drill_contract._validate_backup_metadata(
                str(stable_metadata),
                backup=stable_dump,
                environment="staging",
                workspace_root=ROOT,
            )
        )
        assert stable_dump.name == "backup.dump"
        assert stable_metadata.name == "backup.json"
        assert validated_metadata == stable_metadata
        assert release_id == "a" * 40
        assert dump_sha256 == hashlib.sha256(stable_dump.read_bytes()).hexdigest()
        assert metadata_sha256 == hashlib.sha256(stable_metadata.read_bytes()).hexdigest()
    finally:
        proof.remove_restore_directory(stable_dir, restore_root)
        proof.remove_restore_directory(restored_dir, restore_root)


def test_restore_drill_invocation_is_execute_only_and_uses_immutable_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    evidence_path = evidence_dir / "restore-drill-0123456789ab.json"
    release = proof.ApplicationRelease(
        "staging",
        tmp_path / ("a" * 40),
        tmp_path / "scripts" / "restore-drill.py",
        "sha256:" + "b" * 64,
    )
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], *_args, **kwargs: object) -> str:
        calls.append(command)
        return json.dumps({"result": "passed", "evidence": str(evidence_path)})

    monkeypatch.setattr(proof, "_run", fake_run)
    monkeypatch.setattr(proof, "_validate_drill_evidence", lambda *_args: None)
    returned = proof._invoke_restore_drill(
        release,
        "staging",
        tmp_path / "backup.dump",
        tmp_path / "backup.json",
        evidence_dir,
    )
    assert returned == evidence_path
    assert calls[0][0:2] == ("python3", str(release.restore_drill))
    assert "--execute" in calls[0]
    assert "--acknowledge-isolated-target" in calls[0]
    assert "--application-image" in calls[0]


def test_restored_row_count_parity_is_fail_closed(tmp_path: Path) -> None:
    evidence = tmp_path / "restore-drill.json"
    expected = {table: 0 for table in proof.PARITY_TABLES}
    evidence.write_text(json.dumps({"row_counts": expected}), encoding="utf-8")
    proof._verify_row_count_parity(evidence, expected)
    expected["persons"] = 1
    with pytest.raises(proof.RestoreProofError, match="parity"):
        proof._verify_row_count_parity(evidence, expected)


def test_run_restores_pair_then_delegates_and_always_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime.now(dt.UTC)
    restore_root = tmp_path / "restore-root"
    evidence_root = tmp_path / "evidence-root"
    release = proof.ApplicationRelease(
        "staging", tmp_path / ("a" * 40), tmp_path / "restore-drill.py", "sha256:" + "b" * 64
    )
    monkeypatch.setattr(proof, "resolve_current_release", lambda _environment: release)
    monkeypatch.setattr(proof, "_validate_drill_evidence", lambda *_args: None)
    fsynced: list[Path] = []
    monkeypatch.setattr(proof, "_fsync_directory", fsynced.append)
    calls: list[list[str]] = []

    def fake_run(
        command: Sequence[str], *_args, capture_stdout: bool = False, **_kwargs: object
    ) -> str:
        command = list(command)
        calls.append(command)
        if command[1] == "snapshots":
            return _snapshot(now)
        if command[1] == "ls":
            return _tree()
        if command[1] == "restore":
            restore_dir = Path(command[command.index("--target") + 1])
            _write_pair(restore_dir)
            return ""
        evidence_dir = Path(command[command.index("--evidence-dir") + 1])
        evidence_dir.mkdir(parents=True)
        evidence_path = evidence_dir / "restore-drill-0123456789ab.json"
        evidence_path.write_text(
            json.dumps({"row_counts": {table: 0 for table in proof.PARITY_TABLES}}),
            encoding="utf-8",
        )
        return json.dumps({"result": "passed", "evidence": str(evidence_path)})

    monkeypatch.setattr(proof, "_run", fake_run)
    returned = proof.run("staging", restore_root=restore_root, evidence_root=evidence_root, now=now)
    assert returned.parent == evidence_root
    assert not list(restore_root.iterdir())
    record = json.loads((returned / "off-site-restore-proof.json").read_text(encoding="utf-8"))
    assert record["restic_snapshot_id"] == "a" * 64
    assert record["snapshot_pair"]["dump_path"].endswith("/backup.dump")
    assert fsynced == [returned]
    assert [call[1] for call in calls[:3]] == ["snapshots", "ls", "restore"]
    assert calls[0] == [
        "restic",
        "snapshots",
        "--json",
        "--tag",
        f"{proof.RESTIC_TAG},environment=staging",
    ]
    assert calls[-1][0:2] == ["python3", str(release.restore_drill)]


def test_run_rejects_backup_from_a_different_immutable_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime.now(dt.UTC)
    restore_root = tmp_path / "restore-root"
    evidence_root = tmp_path / "evidence-root"
    release = proof.ApplicationRelease(
        "staging", tmp_path / ("b" * 40), tmp_path / "restore-drill.py", "sha256:" + "b" * 64
    )
    monkeypatch.setattr(proof, "resolve_current_release", lambda _environment: release)

    def fake_run(command: Sequence[str], *_args, **_kwargs: object) -> str:
        if command[1] == "snapshots":
            return _snapshot(now)
        if command[1] == "ls":
            return _tree()
        restore_dir = Path(command[command.index("--target") + 1])
        _write_pair(restore_dir)
        return ""

    monkeypatch.setattr(proof, "_run", fake_run)
    with pytest.raises(proof.RestoreProofError, match="does not match"):
        proof.run("staging", restore_root=restore_root, evidence_root=evidence_root, now=now)
    assert not list(restore_root.iterdir())


def test_units_manifest_and_wrapper_are_narrow_and_hardened() -> None:
    manifest = (FOUNDATION / "config" / "release" / "install-manifest.tsv").read_text(
        encoding="utf-8"
    )
    assert "scripts/ac-restic-postgres-restore-proof\t" in manifest
    assert "scripts/ac-restic-postgres-restore-proof-inner\t" in manifest
    assert "scripts/ac-restic-postgres-restore-proof.py\t" in manifest
    assert "config/systemd/ac-restic-postgres-restore-proof@.service\t" in manifest
    assert "config/systemd/ac-restic-postgres-restore-proof@.timer\t" in manifest

    wrapper = (FOUNDATION / "scripts" / "ac-restic-postgres-restore-proof").read_text(
        encoding="utf-8"
    )
    assert "ac-infisical-run-backup" in wrapper
    assert "ac-restic-postgres-restore-proof-inner" in wrapper
    assert "--environment {staging|production}" in wrapper

    inner = (FOUNDATION / "scripts" / "ac-restic-postgres-restore-proof-inner").read_text(
        encoding="utf-8"
    )
    for marker in (
        'export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"',
        'export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"',
        "export RESTIC_CACHE_DIR='/var/cache/authority-closers-restic'",
        'exec 9>>"$restic_lock_file"',
        "flock --exclusive --nonblock 9",
        "ac-restic-postgres-restore-proof.py",
    ):
        assert marker in inner

    service = (
        FOUNDATION / "config" / "systemd" / "ac-restic-postgres-restore-proof@.service"
    ).read_text(encoding="utf-8")
    for marker in (
        "After=network-online.target docker.service",
        "Requires=docker.service",
        "User=root",
        "Environment=DOCKER_CONFIG=/run/ac-docker-cli",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "PrivateTmp=true",
        "ReadWritePaths=/srv/authority-closers/recovery-tmp",
        (
            "ReadWritePaths=/srv/authority-closers/recovery-tmp "
            "/srv/authority-closers/recovery-evidence"
        ),
        "TimeoutStartSec=75min",
    ):
        assert marker in service
    assert "ports:" not in service

    bootstrap = (FOUNDATION / "scripts" / "bootstrap-host.sh").read_text(encoding="utf-8")
    assert "/srv/authority-closers/recovery-tmp" in bootstrap
    assert "/srv/authority-closers/recovery-evidence" in bootstrap

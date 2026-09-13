from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from ac_platform.recovery.restore_drill_probe import ProbeError, validate_probe_target

SCRIPT = Path(__file__).parents[2] / "infra" / "application" / "scripts" / "restore-drill.py"
ROOT = Path(__file__).parents[2]
PROBE = (
    Path(__file__).parents[2]
    / "packages"
    / "python"
    / "ac_platform"
    / "recovery"
    / "restore_drill_probe.py"
)
SPEC = importlib.util.spec_from_file_location("restore_drill", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
restore_drill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = restore_drill
SPEC.loader.exec_module(restore_drill)

APPLICATION_IMAGE = "sha256:" + "a" * 64
CURRENT_MIGRATION_HEAD = restore_drill._migration_head_from_source(ROOT)
GIT = shutil.which("git")
assert GIT is not None
DOCKER = shutil.which("docker.exe") or shutil.which("docker")
CURRENT_RELEASE_ID = subprocess.run(  # noqa: S603 - fixed read-only Git command
    [GIT, "-C", str(ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
    capture_output=True,
    check=True,
    text=True,
).stdout.strip()


def _write_backup_pair(
    directory: Path,
    *,
    environment: str = "staging",
    release_id: str = CURRENT_RELEASE_ID,
    migration_head: str = CURRENT_MIGRATION_HEAD,
) -> tuple[Path, Path, Any]:
    backup = directory / f"capture-{environment}.dump"
    backup.write_bytes(b"PGDMP-test-fixture")
    captured_at = restore_drill._now() - timedelta(minutes=1)
    metadata = backup.with_suffix(".json")
    metadata.write_text(
        json.dumps(
            {
                "artifact_type": "authority-closers-postgresql-logical",
                "restic_tag": "authority-closers-postgres-logical",
                "environment": environment,
                "release_id": release_id,
                "compose_project": f"ac-application-{environment}",
                "database_role": "ac_backup",
                "format": "custom",
                "verification": "pg_restore --list",
                "capture_started_at": (captured_at - timedelta(seconds=1)).isoformat(),
                "capture_completed_at": captured_at.isoformat(),
                "captured_at": captured_at.isoformat(),
                "captured_at_epoch_ns": int(captured_at.timestamp() * 1_000_000_000),
                "capture_clock": "CLOCK_REALTIME",
                "dump_bytes": backup.stat().st_size,
                "dump_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                "parity_contract": restore_drill.parity_contract_for_head(migration_head),
                "migration_head": migration_head,
                "row_counts": {
                    table: 0 for table in restore_drill.parity_tables_for_head(migration_head)
                },
            }
        ),
        encoding="utf-8",
    )
    return backup, metadata, captured_at


def _config(tmp_path: Path, *, execute: bool = False) -> Any:
    backup, metadata, captured_at = _write_backup_pair(tmp_path)
    return restore_drill.DrillConfig(
        environment="staging",
        backup=backup,
        backup_metadata=metadata,
        backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
        backup_metadata_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),
        backup_captured_at=captured_at,
        backup_release_id=CURRENT_RELEASE_ID,
        evidence_dir=tmp_path / "evidence",
        workspace_mode="source",
        workspace_release_id=CURRENT_RELEASE_ID,
        expected_migration_head=CURRENT_MIGRATION_HEAD,
        postgres_image=restore_drill.DEFAULT_POSTGRES_IMAGE,
        application_image=APPLICATION_IMAGE,
        execute=execute,
        acknowledge_isolated_target=execute,
        reconcile_job_ids=(),
        reconcile_outbox_event_ids=(),
        reconcile_actor_person_id=None,
        reconcile_tenant_id=None,
        reconcile_reason=None,
        acknowledge_reconciliation=False,
    )


def _rehearsal_config(tmp_path: Path, *, execute: bool = False) -> Any:
    source_release_id = "b" * 40
    backup, metadata, captured_at = _write_backup_pair(
        tmp_path,
        release_id=source_release_id,
        migration_head=restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD,
    )
    return restore_drill.DrillConfig(
        environment="staging",
        backup=backup,
        backup_metadata=metadata,
        backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
        backup_metadata_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),
        backup_captured_at=captured_at,
        backup_release_id=source_release_id,
        evidence_dir=tmp_path / "evidence",
        workspace_mode="source",
        workspace_release_id=CURRENT_RELEASE_ID,
        expected_migration_head=restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD,
        postgres_image=restore_drill.DEFAULT_POSTGRES_IMAGE,
        application_image=APPLICATION_IMAGE,
        execute=execute,
        acknowledge_isolated_target=execute,
        reconcile_job_ids=(),
        reconcile_outbox_event_ids=(),
        reconcile_actor_person_id=None,
        reconcile_tenant_id=None,
        reconcile_reason=None,
        acknowledge_reconciliation=False,
        source_application_image="sha256:" + "b" * 64,
        source_migration_head=restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD,
    )


def _sales_xray_rehearsal_config(tmp_path: Path, *, execute: bool = False) -> Any:
    source_release_id = "c" * 40
    backup, metadata, captured_at = _write_backup_pair(
        tmp_path,
        release_id=source_release_id,
        migration_head=restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
    )
    return restore_drill.DrillConfig(
        environment="staging",
        backup=backup,
        backup_metadata=metadata,
        backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
        backup_metadata_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),
        backup_captured_at=captured_at,
        backup_release_id=source_release_id,
        evidence_dir=tmp_path / "evidence",
        workspace_mode="source",
        workspace_release_id=CURRENT_RELEASE_ID,
        expected_migration_head=restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD,
        postgres_image=restore_drill.DEFAULT_POSTGRES_IMAGE,
        application_image=APPLICATION_IMAGE,
        execute=execute,
        acknowledge_isolated_target=execute,
        reconcile_job_ids=(),
        reconcile_outbox_event_ids=(),
        reconcile_actor_person_id=None,
        reconcile_tenant_id=None,
        reconcile_reason=None,
        acknowledge_reconciliation=False,
        source_application_image="sha256:" + "c" * 64,
        source_migration_head=restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
    )


def _run_git(repository: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603 - isolated test repository only
        [GIT, "-C", str(repository), *args],
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def _create_clean_source_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "source"
    migration_dir = repository / "db" / "migrations" / "versions"
    migration_dir.mkdir(parents=True)
    (repository / "AGENTS.md").write_text("# Test repository\n", encoding="utf-8")
    (migration_dir / "20260830_9999_test.py").write_text(
        'revision = "20260830_9999"\ndown_revision = None\n',
        encoding="utf-8",
    )
    _run_git(repository, "init")
    _run_git(repository, "config", "user.email", "test@example.invalid")
    _run_git(repository, "config", "user.name", "Restore Drill Test")
    _run_git(repository, "add", "--all")
    _run_git(repository, "commit", "-m", "test fixture")
    return repository


def _allow_test_owned_stable_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "posix":
        monkeypatch.setattr(restore_drill.os, "geteuid", lambda: 0, raising=False)
        monkeypatch.setattr(restore_drill, "_path_is_root_owned", lambda _path: True)


def test_host_script_is_stdlib_only_and_uses_application_probe_boundary() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    probe_source = PROBE.read_text(encoding="utf-8")

    assert "sqlalchemy" not in source.lower()
    assert "ac_platform.recovery.restore_drill_probe" in source
    assert "mark_database_restore" in probe_source
    assert "reconcile_operations" in probe_source
    assert "DurableWorker" in probe_source
    assert '"--internal"' in source
    assert "127.0.0.1::5432" not in source
    assert "destination=/restore/backup.dump,readonly" in source
    assert "provider_calls" in probe_source


def test_migration_head_tracks_source_and_reviewed_release_contract(tmp_path: Path) -> None:
    assert restore_drill._expected_migration_head(ROOT) == CURRENT_MIGRATION_HEAD

    release = tmp_path / "release"
    release.mkdir()
    (release / "release-images.env").write_text(
        f"AC_MIGRATION_HEAD={CURRENT_MIGRATION_HEAD}\n",
        encoding="utf-8",
    )
    assert restore_drill._expected_migration_head(release) == CURRENT_MIGRATION_HEAD


def test_source_workspace_contract_binds_git_release_and_migration_head(tmp_path: Path) -> None:
    repository = _create_clean_source_repository(tmp_path)
    expected_release_id = _run_git(repository, "rev-parse", "--verify", "HEAD^{commit}")

    mode, release_id, migration_head = restore_drill._workspace_release_contract(repository)

    assert mode == "source"
    assert release_id == expected_release_id
    assert migration_head == "20260830_9999"


@pytest.mark.parametrize("dirty_state", ("unstaged", "staged", "untracked"))
def test_source_workspace_contract_rejects_every_dirty_state(
    tmp_path: Path,
    dirty_state: str,
) -> None:
    repository = _create_clean_source_repository(tmp_path)
    agents = repository / "AGENTS.md"
    if dirty_state == "unstaged":
        agents.write_text("# Modified test repository\n", encoding="utf-8")
    elif dirty_state == "staged":
        agents.write_text("# Staged test repository\n", encoding="utf-8")
        _run_git(repository, "add", "AGENTS.md")
    else:
        (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(restore_drill.DrillError, match="staged, unstaged, or untracked"):
        restore_drill._workspace_release_contract(repository)


def test_release_workspace_contract_binds_commit_manifest_and_head(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "RELEASE-COMMIT").write_text(f"{CURRENT_RELEASE_ID}\n", encoding="ascii")
    (release / "release-images.env").write_text(
        f"AC_RELEASE_ID={CURRENT_RELEASE_ID}\nAC_MIGRATION_HEAD={CURRENT_MIGRATION_HEAD}\n",
        encoding="ascii",
    )

    assert restore_drill._workspace_release_contract(release) == (
        "release",
        CURRENT_RELEASE_ID,
        CURRENT_MIGRATION_HEAD,
    )


def test_image_contract_requires_one_exact_release_marker_and_migration_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = restore_drill._target_for("0123456789ab")
    outputs = iter((f"{CURRENT_RELEASE_ID}\n", f"{CURRENT_MIGRATION_HEAD} (head)\n"))
    commands: list[tuple[str, ...]] = []
    removed: list[tuple[str, str, str]] = []

    def run_docker(args: tuple[str, ...], *_args: object, **_kwargs: object) -> str:
        commands.append(args)
        return next(outputs)

    monkeypatch.setattr(restore_drill, "_run_docker_output", run_docker)
    monkeypatch.setattr(
        restore_drill,
        "_remove_labeled_resource",
        lambda kind, name, run_id: removed.append((kind, name, run_id)),
    )

    assert restore_drill._application_image_contract(APPLICATION_IMAGE, target) == (
        CURRENT_RELEASE_ID,
        CURRENT_MIGRATION_HEAD,
    )
    assert {command[command.index("--name") + 1] for command in commands} == {
        target.probe_container,
        target.init_container,
    }
    assert all(command[command.index("--label") + 1] == target.label for command in commands)
    assert removed == [
        ("container", target.probe_container, target.run_id),
        ("container", target.init_container, target.run_id),
    ]


@pytest.mark.parametrize(
    "release_output,heads_output,error",
    (
        (f" {CURRENT_RELEASE_ID}\n", f"{CURRENT_MIGRATION_HEAD} (head)\n", "release marker"),
        (f"{CURRENT_RELEASE_ID}\n\n", f"{CURRENT_MIGRATION_HEAD} (head)\n", "release marker"),
        (f"{CURRENT_RELEASE_ID}\n", f"{CURRENT_MIGRATION_HEAD} (head)\n\n", "exactly one"),
    ),
)
def test_image_contract_rejects_normalized_or_extra_output(
    monkeypatch: pytest.MonkeyPatch,
    release_output: str,
    heads_output: str,
    error: str,
) -> None:
    target = restore_drill._target_for("0123456789ab")
    outputs = iter((release_output, heads_output))
    monkeypatch.setattr(
        restore_drill,
        "_run_docker_output",
        lambda *_args, **_kwargs: next(outputs),
    )
    monkeypatch.setattr(restore_drill, "_remove_labeled_resource", lambda *_args: None)

    with pytest.raises(restore_drill.DrillError, match=error):
        restore_drill._application_image_contract(APPLICATION_IMAGE, target)


@pytest.mark.parametrize(
    "image_release_id,image_heads,error",
    (
        ("b" * 40, f"{CURRENT_MIGRATION_HEAD} (head)", "release marker"),
        (CURRENT_RELEASE_ID, "20000101_0001 (head)", "migration head"),
        (
            CURRENT_RELEASE_ID,
            f"{CURRENT_MIGRATION_HEAD} (head)\n20000101_0001 (head)",
            "exactly one",
        ),
    ),
)
def test_source_preflight_rejects_image_release_or_head_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_release_id: str,
    image_heads: str,
    error: str,
) -> None:
    config = _config(tmp_path, execute=True)
    monkeypatch.setattr(
        restore_drill,
        "_run_docker",
        lambda args, *_positional, **_kwargs: (
            config.application_image
            if args[:3] == ("image", "inspect", "--format") and args[-1] == config.application_image
            else "fixture"
        ),
    )
    monkeypatch.setattr(
        restore_drill,
        "_application_image_contract",
        lambda _image, _target: (image_release_id, image_heads.removesuffix(" (head)")),
    )
    if "\n" in image_heads:
        monkeypatch.setattr(
            restore_drill,
            "_application_image_contract",
            lambda _image, _target: (_ for _ in ()).throw(
                restore_drill.DrillError("application image must report exactly one migration head")
            ),
        )
    monkeypatch.setattr(restore_drill, "_docker_inspect_optional", lambda *_args: None)

    with pytest.raises(restore_drill.DrillError, match=error):
        restore_drill._preflight(restore_drill._target_for("0123456789ab"), config)


def test_migration_rehearsal_preflight_binds_source_and_candidate_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _rehearsal_config(tmp_path, execute=True)
    source_image = config.source_application_image
    assert source_image is not None

    monkeypatch.setattr(
        restore_drill,
        "_run_docker",
        lambda args, *_positional, **_kwargs: (
            args[-1] if args[:3] == ("image", "inspect", "--format") else "fixture"
        ),
    )
    monkeypatch.setattr(restore_drill, "_docker_inspect_optional", lambda *_args: None)

    def image_contract(image: str, _target: Any) -> tuple[str, str]:
        if image == source_image:
            return "b" * 40, restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD
        return CURRENT_RELEASE_ID, restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD

    monkeypatch.setattr(restore_drill, "_application_image_contract", image_contract)

    restore_drill._preflight(restore_drill._target_for("0123456789ab"), config)


def test_migration_rehearsal_preflight_rejects_source_image_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _rehearsal_config(tmp_path, execute=True)
    source_image = config.source_application_image
    assert source_image is not None

    def inspect_image(args: tuple[str, ...], *_positional: object, **_kwargs: object) -> str:
        if args[:3] != ("image", "inspect", "--format"):
            return "fixture"
        if args[-1] == source_image:
            return "sha256:" + "c" * 64
        return args[-1]

    monkeypatch.setattr(
        restore_drill,
        "_run_docker",
        inspect_image,
    )

    with pytest.raises(restore_drill.DrillError, match="source application image identity"):
        restore_drill._preflight(restore_drill._target_for("0123456789ab"), config)


def test_sales_xray_rehearsal_preflight_binds_0029_source_and_0030_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sales_xray_rehearsal_config(tmp_path, execute=True)
    source_image = config.source_application_image
    assert source_image is not None

    monkeypatch.setattr(
        restore_drill,
        "_run_docker",
        lambda args, *_positional, **_kwargs: (
            args[-1] if args[:3] == ("image", "inspect", "--format") else "fixture"
        ),
    )
    monkeypatch.setattr(restore_drill, "_docker_inspect_optional", lambda *_args: None)

    def image_contract(image: str, _target: Any) -> tuple[str, str]:
        if image == source_image:
            return "c" * 40, restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD
        return CURRENT_RELEASE_ID, restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD

    monkeypatch.setattr(restore_drill, "_application_image_contract", image_contract)

    restore_drill._preflight(restore_drill._target_for("0123456789ab"), config)


def test_migration_rehearsal_config_keeps_prior_backup_and_candidate_workspace_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        restore_drill,
        "_workspace_release_contract",
        lambda _root: ("source", CURRENT_RELEASE_ID, restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD),
    )
    backup, metadata, _captured_at = _write_backup_pair(
        tmp_path,
        release_id="b" * 40,
        migration_head=restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD,
    )
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "staging",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--application-image",
            APPLICATION_IMAGE,
            "--source-application-image",
            "sha256:" + "b" * 64,
            "--source-migration-head",
            restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD,
        ]
    )

    config = restore_drill._config_from_args(args)

    assert config.backup_release_id == "b" * 40
    assert config.workspace_release_id == CURRENT_RELEASE_ID
    assert config.expected_migration_head == restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD
    assert config.source_application_image == "sha256:" + "b" * 64
    assert config.source_migration_head == restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD


def test_sales_xray_rehearsal_config_accepts_only_populated_0029_to_0030(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        restore_drill,
        "_workspace_release_contract",
        lambda _root: (
            "source",
            CURRENT_RELEASE_ID,
            restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD,
        ),
    )
    backup, metadata, _captured_at = _write_backup_pair(
        tmp_path,
        release_id="c" * 40,
        migration_head=restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
    )
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "staging",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--application-image",
            APPLICATION_IMAGE,
            "--source-application-image",
            "sha256:" + "c" * 64,
            "--source-migration-head",
            restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
        ]
    )

    config = restore_drill._config_from_args(args)

    assert config.backup_release_id == "c" * 40
    assert config.expected_migration_head == restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD
    assert config.source_migration_head == restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD


def test_direct_sales_xray_rehearsal_config_accepts_0029_to_0031(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        restore_drill,
        "_workspace_release_contract",
        lambda _root: (
            "source",
            CURRENT_RELEASE_ID,
            restore_drill.DIRECT_SALES_XRAY_REHEARSAL_TARGET_HEAD,
        ),
    )
    backup, metadata, _captured_at = _write_backup_pair(
        tmp_path,
        environment="production",
        release_id="d" * 40,
        migration_head=restore_drill.DIRECT_SALES_XRAY_REHEARSAL_SOURCE_HEAD,
    )
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "production",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--application-image",
            APPLICATION_IMAGE,
            "--source-application-image",
            "sha256:" + "d" * 64,
            "--source-migration-head",
            restore_drill.DIRECT_SALES_XRAY_REHEARSAL_SOURCE_HEAD,
        ]
    )

    config = restore_drill._config_from_args(args)

    assert config.backup_release_id == "d" * 40
    assert config.expected_migration_head == (restore_drill.DIRECT_SALES_XRAY_REHEARSAL_TARGET_HEAD)
    assert config.source_migration_head == (restore_drill.DIRECT_SALES_XRAY_REHEARSAL_SOURCE_HEAD)


def test_processing_plan_rehearsal_config_accepts_populated_0031_to_0032(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        restore_drill,
        "_workspace_release_contract",
        lambda _root: (
            "source",
            CURRENT_RELEASE_ID,
            restore_drill.PLANS_REHEARSAL_TARGET_HEAD,
        ),
    )
    backup, metadata, _captured_at = _write_backup_pair(
        tmp_path,
        release_id="e" * 40,
        migration_head=restore_drill.PLANS_REHEARSAL_SOURCE_HEAD,
    )
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "staging",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--application-image",
            APPLICATION_IMAGE,
            "--source-application-image",
            "sha256:" + "e" * 64,
            "--source-migration-head",
            restore_drill.PLANS_REHEARSAL_SOURCE_HEAD,
        ]
    )

    config = restore_drill._config_from_args(args)

    assert config.backup_release_id == "e" * 40
    assert config.expected_migration_head == restore_drill.PLANS_REHEARSAL_TARGET_HEAD
    assert config.source_migration_head == restore_drill.PLANS_REHEARSAL_SOURCE_HEAD


def test_processing_ownership_rehearsal_config_accepts_0036_to_0037(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        restore_drill,
        "_workspace_release_contract",
        lambda _root: (
            "source",
            CURRENT_RELEASE_ID,
            restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_TARGET_HEAD,
        ),
    )
    backup, metadata, _captured_at = _write_backup_pair(
        tmp_path,
        release_id="f" * 40,
        migration_head=restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_SOURCE_HEAD,
    )
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "staging",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--application-image",
            APPLICATION_IMAGE,
            "--source-application-image",
            "sha256:" + "f" * 64,
            "--source-migration-head",
            restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_SOURCE_HEAD,
        ]
    )

    config = restore_drill._config_from_args(args)

    assert config.backup_release_id == "f" * 40
    assert config.expected_migration_head == (
        restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_TARGET_HEAD
    )
    assert config.source_application_image == "sha256:" + "f" * 64
    assert config.source_migration_head == (
        restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_SOURCE_HEAD
    )


def test_processing_ownership_parity_contract_tracks_0037_tables() -> None:
    assert restore_drill.parity_contract_for_head("20260914_0037") == ("ac-postgres-parity-v17")
    assert restore_drill.parity_tables_for_head("20260914_0037") == (
        restore_drill.ACQUISITION_PARITY_TABLES
        + restore_drill.PROCESSING_OWNERSHIP_PARITY_NEW_TABLES
    )
    assert (
        restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_SOURCE_HEAD,
        restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_TARGET_HEAD,
    ) in restore_drill.MIGRATION_REHEARSAL_PAIRS


def test_processing_ownership_migration_command_targets_only_0037() -> None:
    target = restore_drill._target_for("0123456789ab")
    command = restore_drill._migration_command(
        target,
        APPLICATION_IMAGE,
        target_head=restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_TARGET_HEAD,
    )

    assert command[-3:] == (
        APPLICATION_IMAGE,
        "upgrade",
        restore_drill.PROCESSING_OWNERSHIP_REHEARSAL_TARGET_HEAD,
    )
    assert "--publish" not in command
    assert "--privileged" not in command
    assert target.password not in command


def test_migration_rehearsal_transition_requires_exact_preservation_and_derivations() -> None:
    source_counts = {
        table: 0
        for table in restore_drill.parity_tables_for_head(
            restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD
        )
    }
    source_counts["academy_public_profiles"] = 3
    derivations = {
        "academy_public_profiles": 3,
        "academy_public_profile_people": 2,
    }
    target_counts = dict(source_counts)
    target_counts.update(
        {
            "community_public_profiles": 2,
            "academy_leaderboard_preferences": 3,
            "app_update_read_receipts": 0,
        }
    )

    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        derivations,
    ) == {
        "community_public_profiles": 2,
        "academy_leaderboard_preferences": 3,
        "app_update_read_receipts": 0,
    }

    target_counts["academy_leaderboard_preferences"] = 2
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            derivations,
        )


def test_sales_xray_transition_preserves_populated_0029_and_requires_empty_new_tables() -> None:
    source_head = restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD
    source_counts = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target_counts = dict(source_counts)
    target_counts.update({table: 0 for table in restore_drill.SALES_XRAY_PARITY_NEW_TABLES})

    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        {},
        source_head=source_head,
        target_head=target_head,
    ) == {table: 0 for table in restore_drill.SALES_XRAY_PARITY_NEW_TABLES}

    target_counts[restore_drill.SALES_XRAY_PARITY_NEW_TABLES[0]] = 1
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            {},
            source_head=source_head,
            target_head=target_head,
        )


def test_inference_transition_preserves_populated_0030_and_requires_empty_new_table() -> None:
    source_head = restore_drill.INFERENCE_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.INFERENCE_REHEARSAL_TARGET_HEAD
    source_counts = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target_counts = dict(source_counts)
    target_counts.update({table: 0 for table in restore_drill.INFERENCE_PARITY_NEW_TABLES})

    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        {},
        source_head=source_head,
        target_head=target_head,
    ) == {table: 0 for table in restore_drill.INFERENCE_PARITY_NEW_TABLES}

    target_counts[restore_drill.INFERENCE_PARITY_NEW_TABLES[0]] = 1
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            {},
            source_head=source_head,
            target_head=target_head,
        )


def test_processing_plan_transition_preserves_0031_and_requires_empty_tables() -> None:
    source_head = restore_drill.PLANS_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.PLANS_REHEARSAL_TARGET_HEAD
    source_counts = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target_counts = dict(source_counts)
    target_counts.update({table: 0 for table in restore_drill.PLANS_PARITY_NEW_TABLES})

    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        {},
        source_head=source_head,
        target_head=target_head,
    ) == {table: 0 for table in restore_drill.PLANS_PARITY_NEW_TABLES}

    target_counts[restore_drill.PLANS_PARITY_NEW_TABLES[0]] = 1
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            {},
            source_head=source_head,
            target_head=target_head,
        )


def test_community_connections_transition_preserves_0032_and_requires_empty_tables() -> None:
    source_head = restore_drill.COMMUNITY_CONNECTIONS_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.COMMUNITY_CONNECTIONS_REHEARSAL_TARGET_HEAD
    source_counts = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target_counts = dict(source_counts)
    target_counts.update(
        {table: 0 for table in restore_drill.COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES}
    )

    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        {},
        source_head=source_head,
        target_head=target_head,
    ) == {table: 0 for table in restore_drill.COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES}

    target_counts[restore_drill.COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES[0]] = 1
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            {},
            source_head=source_head,
            target_head=target_head,
        )


def test_review_assignment_transition_preserves_0033_and_requires_empty_tables() -> None:
    source_head = restore_drill.REVIEWS_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.REVIEWS_REHEARSAL_TARGET_HEAD
    source_counts = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target_counts = dict(source_counts)
    target_counts.update({table: 0 for table in restore_drill.REVIEWS_PARITY_NEW_TABLES})

    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        {},
        source_head=source_head,
        target_head=target_head,
    ) == {table: 0 for table in restore_drill.REVIEWS_PARITY_NEW_TABLES}

    target_counts[restore_drill.REVIEWS_PARITY_NEW_TABLES[0]] = 1
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            {},
            source_head=source_head,
            target_head=target_head,
        )


@pytest.mark.parametrize(
    ("source_head", "target_head", "new_tables"),
    (
        (
            "20260913_0034",
            "20260913_0035",
            (
                "conversation_review_invitations",
                "conversation_review_invitation_revocations",
                "conversation_review_invitation_acceptances",
            ),
        ),
        (
            "20260913_0035",
            "20260914_0036",
            (
                "conversation_visitors",
                "conversation_visitor_claims",
                "conversation_acquisition_usage",
                "conversation_acquisition_settlements",
            ),
        ),
        (
            "20260914_0036",
            "20260914_0037",
            (
                "conversation_processing_principals",
                "conversation_processing_leases",
                "conversation_guest_submissions",
            ),
        ),
    ),
)
def test_invitation_and_guest_migrations_preserve_existing_history(
    source_head: str, target_head: str, new_tables: tuple[str, ...]
) -> None:
    source = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target = source | dict.fromkeys(new_tables, 0)
    assert restore_drill._assert_migration_rehearsal_transition(
        source, target, {}, source_head=source_head, target_head=target_head
    ) == dict.fromkeys(new_tables, 0)
    for table in new_tables:
        with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
            restore_drill._assert_migration_rehearsal_transition(
                source, target | {table: 1}, {}, source_head=source_head, target_head=target_head
            )
        incomplete = {key: value for key, value in target.items() if key != table}
        with pytest.raises(restore_drill.DrillError, match="incomplete"):
            restore_drill._assert_migration_rehearsal_transition(
                source, incomplete, {}, source_head=source_head, target_head=target_head
            )
    with pytest.raises(restore_drill.DrillError, match="preserved source"):
        restore_drill._assert_migration_rehearsal_transition(
            source, target | {"persons": 2}, {}, source_head=source_head, target_head=target_head
        )


def test_direct_sales_xray_transition_preserves_0029_and_requires_all_new_tables_empty() -> None:
    source_head = restore_drill.DIRECT_SALES_XRAY_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.DIRECT_SALES_XRAY_REHEARSAL_TARGET_HEAD
    source_counts = {table: 3 for table in restore_drill.parity_tables_for_head(source_head)}
    target_counts = dict(source_counts)
    target_counts.update(
        {table: 0 for table in restore_drill.DIRECT_SALES_XRAY_REHEARSAL_NEW_TABLES}
    )

    assert len(source_counts) == 58
    assert len(target_counts) == 72
    assert restore_drill._assert_migration_rehearsal_transition(
        source_counts,
        target_counts,
        {},
        source_head=source_head,
        target_head=target_head,
    ) == {table: 0 for table in restore_drill.DIRECT_SALES_XRAY_REHEARSAL_NEW_TABLES}

    target_counts[restore_drill.DIRECT_SALES_XRAY_REHEARSAL_NEW_TABLES[-1]] = 1
    with pytest.raises(restore_drill.DrillError, match="new-table row counts"):
        restore_drill._assert_migration_rehearsal_transition(
            source_counts,
            target_counts,
            {},
            source_head=source_head,
            target_head=target_head,
        )


@pytest.mark.parametrize(
    "change",
    (
        "missing_source",
        "missing_target",
        "unexpected_target",
        "changed_existing",
        "boolean_source",
        "negative_target",
        "string_target",
        "unexpected_derivations",
    ),
)
def test_sales_xray_transition_rejects_incomplete_or_changed_evidence(change: str) -> None:
    source_head = restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD
    target_head = restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD
    source: dict[str, Any] = {
        table: 3 for table in restore_drill.parity_tables_for_head(source_head)
    }
    target: dict[str, Any] = dict(source)
    target.update({table: 0 for table in restore_drill.SALES_XRAY_PARITY_NEW_TABLES})
    new_table = restore_drill.SALES_XRAY_PARITY_NEW_TABLES[0]
    derivations: dict[str, int] = {}
    if change == "missing_source":
        source.pop("persons")
    elif change == "missing_target":
        target.pop(new_table)
    elif change == "unexpected_target":
        target["unreviewed_table"] = 0
    elif change == "changed_existing":
        target["persons"] += 1
    elif change == "boolean_source":
        source["persons"] = True
    elif change == "negative_target":
        target[new_table] = -1
    elif change == "string_target":
        target[new_table] = "0"
    else:
        derivations["academy_public_profiles"] = 3
    with pytest.raises(restore_drill.DrillError):
        restore_drill._assert_migration_rehearsal_transition(
            source, target, derivations, source_head=source_head, target_head=target_head
        )


@pytest.mark.parametrize(
    "source_head,target_head",
    (
        (
            restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD,
            restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD,
        ),
        (
            restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
            restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD,
        ),
        (
            restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
            restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD,
        ),
        (restore_drill.SALES_XRAY_REHEARSAL_SOURCE_HEAD, "20260913_0032"),
    ),
)
def test_migration_rehearsal_rejects_unreviewed_pairs(source_head: str, target_head: str) -> None:
    with pytest.raises(restore_drill.DrillError, match="explicitly reviewed"):
        restore_drill._validate_migration_rehearsal_pair(source_head, target_head)


def test_migration_rehearsal_command_runs_only_candidate_alembic_head() -> None:
    target = restore_drill._target_for("0123456789ab")
    command = restore_drill._migration_command(target, APPLICATION_IMAGE)

    assert command[-3:] == (
        APPLICATION_IMAGE,
        "upgrade",
        restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD,
    )
    assert command[command.index("--network") + 1] == target.network
    assert command[command.index("--entrypoint") + 1] == "alembic"
    assert "--publish" not in command
    assert "--privileged" not in command
    assert target.password not in command


def test_sales_xray_migration_command_targets_only_0030() -> None:
    target = restore_drill._target_for("0123456789ab")
    command = restore_drill._migration_command(
        target,
        APPLICATION_IMAGE,
        target_head=restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD,
    )

    assert command[-3:] == (
        APPLICATION_IMAGE,
        "upgrade",
        restore_drill.SALES_XRAY_REHEARSAL_TARGET_HEAD,
    )
    assert "--publish" not in command
    assert "--privileged" not in command


def test_migration_rehearsal_dry_run_is_non_mutating_and_explicit(tmp_path: Path) -> None:
    config = _rehearsal_config(tmp_path)

    plan = restore_drill._dry_run_plan(config)

    assert plan["mode"] == "migration-rehearsal-dry-run"
    assert plan["source_application_image"] == config.source_application_image
    assert plan["source_migration_head"] == restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD
    assert plan["migration"]["command"] == [
        "upgrade",
        restore_drill.MIGRATION_REHEARSAL_TARGET_HEAD,
    ]
    assert plan["external_connections"] == []
    assert not config.evidence_dir.exists()


def test_post_migration_held_probe_requires_same_generation_and_zero_provider_calls() -> None:
    payload = {
        "action": "prove-held",
        "recovery_state": {"generation": 4, "status": "held"},
        "worker_hold_proof": {
            "worker_ready": False,
            "run_once_rejected": True,
            "provider_calls": 0,
        },
    }

    result = restore_drill._validate_held_probe(payload, expected_generation=4)

    assert result["recovery_state"] == {"generation": 4, "status": "held"}
    with pytest.raises(restore_drill.DrillError, match="unexpected recovery generation"):
        restore_drill._validate_held_probe(payload, expected_generation=5)


def test_checked_in_migrations_preserve_forward_only_recovery_policy() -> None:
    migration_dir = ROOT / "db" / "migrations" / "versions"
    migrations = sorted(
        path for path in migration_dir.glob("*.py") if not path.name.startswith("_")
    )
    assert migrations
    for index, migration_path in enumerate(migrations):
        spec = importlib.util.spec_from_file_location(
            f"forward_only_migration_{index}", migration_path
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with pytest.raises(RuntimeError, match="forward-only"):
            migration.downgrade()


@pytest.mark.parametrize(
    "manifest",
    (
        "AC_RELEASE_ID=" + "a" * 40 + "\n",
        "AC_MIGRATION_HEAD=not-a-revision\n",
        f"AC_MIGRATION_HEAD={CURRENT_MIGRATION_HEAD}\nAC_MIGRATION_HEAD={CURRENT_MIGRATION_HEAD}\n",
    ),
)
def test_release_migration_head_fails_closed(tmp_path: Path, manifest: str) -> None:
    (tmp_path / "release-images.env").write_text(manifest, encoding="utf-8")

    with pytest.raises(restore_drill.DrillError, match="migration contract"):
        restore_drill._expected_migration_head(tmp_path)


def test_target_names_are_generated_and_fail_closed() -> None:
    target = restore_drill._target_for("0123456789ab")

    restore_drill._validate_target_names(target)
    assert target.container == "ac-restore-drill-0123456789ab"
    assert target.init_container == "ac-restore-drill-0123456789ab-init"
    assert target.probe_container == "ac-restore-drill-0123456789ab-probe"
    assert target.database == "ac_restore_drill_0123456789ab"
    assert target.role == "ac_restore_owner_0123456789ab"
    with pytest.raises(restore_drill.DrillError):
        restore_drill._target_for("not-safe")


def test_docker_run_commands_are_no_pull_bounded_and_do_not_expose_password(
    tmp_path: Path,
) -> None:
    target = restore_drill._target_for("0123456789ab")
    backup = tmp_path / "staging.dump"
    backup.write_bytes(b"PGDMP-test-fixture")
    init = restore_drill._volume_init_command(target, restore_drill.DEFAULT_POSTGRES_IMAGE)
    postgres = restore_drill._postgres_run_command(
        target,
        backup,
        restore_drill.DEFAULT_POSTGRES_IMAGE,
    )
    probe = restore_drill._probe_command(
        target,
        APPLICATION_IMAGE,
        ("mark-and-prove", "--reason", "safe reason"),
    )
    control_tenant_id = UUID("33333333-3333-4333-8333-333333333333")
    reconcile_probe = restore_drill._probe_command(
        target,
        APPLICATION_IMAGE,
        ("reconcile-selected", "--reason", "safe reason"),
        operations_tenant_id=control_tenant_id,
    )

    for command in (init, postgres, probe):
        assert command[0] == "run"
        pull_index = command.index("--pull")
        assert command[pull_index + 1] == "never"
        assert "--cpus" in command
        assert "--memory" in command
        assert "--memory-swap" in command
        assert "--pids-limit" in command
        assert "--shm-size" in command
        assert target.password not in command

    assert init[init.index("--user") : init.index("--user") + 2] == ("--user", "0:0")

    def docker_option_values(command: tuple[str, ...], option: str) -> list[str]:
        values: list[str] = []
        prefix = f"{option}="
        for index, value in enumerate(command):
            if value == option:
                assert index + 1 < len(command), f"{option} is missing its value"
                values.append(command[index + 1])
            elif value.startswith(prefix):
                values.append(value.removeprefix(prefix))
        return values

    cap_adds = docker_option_values(init, "--cap-add")
    cap_drops = docker_option_values(init, "--cap-drop")
    assert cap_adds == ["CHOWN"]
    assert cap_drops == ["ALL"]
    assert not any(value == "--privileged" or value.startswith("--privileged=") for value in init)
    init_script = init[-1]
    assert init_script.index("chown 0:0 /var/lib/postgresql") < init_script.index(
        "chmod 0700 /var/lib/postgresql"
    )
    assert init_script.index("chmod 0700 /var/lib/postgresql") < init_script.index(
        "chown 999:999 /var/lib/postgresql"
    )
    assert init[init.index("--network") : init.index("--network") + 2] == ("--network", "none")
    assert postgres[postgres.index("--user") : postgres.index("--user") + 2] == (
        "--user",
        "999:999",
    )
    assert postgres[postgres.index("--group-add") + 1] == str(backup.stat().st_gid)
    assert "--publish" not in postgres and "-p" not in postgres
    assert "ALL" in postgres
    assert probe[probe.index("--user") : probe.index("--user") + 2] == ("--user", "10001:10001")
    assert "--read-only" in probe
    assert APPLICATION_IMAGE in probe
    assert "AC_RESTORE_DRILL_DATABASE_URL" in probe
    assert "AC_OPERATIONS_TENANT_ID" not in probe
    assert "AC_OPERATIONS_TENANT_ID" in reconcile_probe
    assert str(control_tenant_id) not in reconcile_probe


def test_docker_exec_includes_target_container_and_passes_only_environment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = restore_drill._target_for("0123456789ab")
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def fake_run_docker(
        args: Any,
        _step: str,
        **kwargs: Any,
    ) -> str:
        calls.append((tuple(args), kwargs))
        return ""

    monkeypatch.setattr(restore_drill, "_run_docker", fake_run_docker)

    restore_drill._docker_exec(target, ("pg_restore", "--list", "/restore/backup.dump"), "list")
    restore_drill._docker_exec(
        target,
        ("psql", "-c", "SELECT 1"),
        "query",
        env_updates={"PGPASSWORD": target.password},
    )

    assert calls[0][0][:2] == ("exec", target.container)
    assert calls[1][0][:4] == ("exec", "--env", "PGPASSWORD", target.container)
    assert target.password not in calls[1][0]
    assert calls[1][1]["env_updates"] == {"PGPASSWORD": target.password}


def test_process_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: Any, **_kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=["docker", "version"], timeout=7)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(restore_drill.DrillError, match="timed out after 7 seconds"):
        restore_drill._run_process(
            ("docker", "version"),
            "verify Docker",
            timeout_seconds=7,
        )


def test_application_and_postgres_images_must_be_immutable() -> None:
    assert restore_drill._validate_application_image(APPLICATION_IMAGE) == APPLICATION_IMAGE
    with pytest.raises(restore_drill.DrillError, match="exact sha256"):
        restore_drill._validate_application_image("ghcr.io/example/api:latest")
    with pytest.raises(restore_drill.DrillError, match="pinned by sha256"):
        restore_drill._validate_postgres_image("postgres:18")


def test_application_probe_accepts_only_token_matched_disposable_identity() -> None:
    token = "0123456789ab"  # noqa: S105 - disposable resource identity, not a secret
    password = "generated-test-password"  # noqa: S105
    url = (
        f"postgresql+psycopg://ac_restore_owner_{token}:{password}"
        f"@ac-restore-drill-{token}:5432/ac_restore_drill_{token}"
    )

    target = validate_probe_target(url, restore_drill.PROBE_ACKNOWLEDGEMENT)

    assert target.token == token
    for unsafe in (
        url.replace("ac_restore_drill_0123456789ab", "ac_platform"),
        url.replace("ac-restore-drill-0123456789ab", "postgres"),
        url.replace("ac_restore_owner_0123456789ab", "ac_owner"),
        url.replace("5432", "5433"),
        url + "?sslmode=disable",
    ):
        with pytest.raises(ProbeError):
            validate_probe_target(unsafe, restore_drill.PROBE_ACKNOWLEDGEMENT)
    with pytest.raises(ProbeError, match="acknowledgement"):
        validate_probe_target(url, "not-approved")


def test_full_config_validation_does_not_create_evidence_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restore_drill, "_assert_clean_source_checkout", lambda _root: None)
    backup, metadata, _captured_at = _write_backup_pair(tmp_path)
    evidence = tmp_path / "evidence"
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "staging",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(evidence),
            "--application-image",
            APPLICATION_IMAGE,
            "--execute",
            "--acknowledge-isolated-target",
        ]
    )

    config = restore_drill._config_from_args(args)

    assert config.evidence_dir == evidence.resolve()
    assert not evidence.exists()


def test_source_config_rejects_backup_from_a_different_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restore_drill, "_assert_clean_source_checkout", lambda _root: None)
    backup, metadata, _captured_at = _write_backup_pair(tmp_path, release_id="b" * 40)
    evidence = tmp_path / "evidence"
    args = restore_drill.build_parser().parse_args(
        [
            "--environment",
            "staging",
            "--backup",
            str(backup),
            "--backup-metadata",
            str(metadata),
            "--evidence-dir",
            str(evidence),
            "--application-image",
            APPLICATION_IMAGE,
        ]
    )

    with pytest.raises(restore_drill.DrillError, match="backup release"):
        restore_drill._config_from_args(args)
    assert not evidence.exists()


def test_backup_metadata_must_match_dump_digest_size_and_environment(tmp_path: Path) -> None:
    backup, metadata, _captured_at = _write_backup_pair(tmp_path)
    workspace_root = restore_drill._workspace_root()

    validated, _timestamp, release_id, backup_sha256, metadata_sha256 = (
        restore_drill._validate_backup_metadata(
            str(metadata),
            backup=backup,
            environment="staging",
            workspace_root=workspace_root,
        )
    )
    assert validated == metadata.resolve()
    assert release_id == CURRENT_RELEASE_ID
    assert backup_sha256 == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert metadata_sha256 == hashlib.sha256(metadata.read_bytes()).hexdigest()

    backup.write_bytes(b"PGDMP-different")
    with pytest.raises(restore_drill.DrillError, match="size or digest"):
        restore_drill._validate_backup_metadata(
            str(metadata),
            backup=backup,
            environment="staging",
            workspace_root=workspace_root,
        )


def test_executed_restore_uses_private_immutable_input_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_test_owned_stable_inputs(monkeypatch)
    config = _config(tmp_path, execute=True)
    original_dump = config.backup.read_bytes()
    original_metadata = config.backup_metadata.read_bytes()
    stable_root = tmp_path / "stable-inputs"

    with restore_drill._stable_restore_inputs(config, root=stable_root) as stable_config:
        assert stable_config.backup.parent.parent == stable_root
        assert stable_config.backup.name == "backup.dump"
        assert stable_config.backup_metadata.name == "backup.json"
        assert stable_config.backup.read_bytes() == original_dump
        assert stable_config.backup_metadata.read_bytes() == original_metadata
        if os.name == "posix":
            assert stat.S_IMODE(stable_config.backup.stat().st_mode) == 0o640
            assert stat.S_IMODE(stable_config.backup_metadata.stat().st_mode) == 0o600
        postgres = restore_drill._postgres_run_command(
            restore_drill._target_for("0123456789ab"),
            stable_config.backup,
            restore_drill.DEFAULT_POSTGRES_IMAGE,
        )
        assert postgres[postgres.index("--group-add") + 1] == str(
            stable_config.backup.stat().st_gid
        )
        config.backup.write_bytes(b"PGDMP-mutated-after-validation")
        config.backup_metadata.write_text("{}", encoding="utf-8")
        assert stable_config.backup.read_bytes() == original_dump
        assert stable_config.backup_metadata.read_bytes() == original_metadata

    assert stable_root.is_dir()
    assert tuple(stable_root.iterdir()) == ()


def test_migration_rehearsal_stable_copy_revalidates_the_prior_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_test_owned_stable_inputs(monkeypatch)
    config = _rehearsal_config(tmp_path, execute=True)
    stable_root = tmp_path / "stable-inputs"

    with restore_drill._stable_restore_inputs(config, root=stable_root) as stable_config:
        metadata = json.loads(stable_config.backup_metadata.read_text(encoding="utf-8"))
        assert metadata["migration_head"] == restore_drill.MIGRATION_REHEARSAL_SOURCE_HEAD

    assert stable_root.is_dir()
    assert tuple(stable_root.iterdir()) == ()


def test_stable_restore_rejects_replacement_pair_with_same_release_and_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_test_owned_stable_inputs(monkeypatch)
    config = _config(tmp_path, execute=True)
    replacement_dump = b"PGDMP-replacement-pair"
    metadata = json.loads(config.backup_metadata.read_text(encoding="utf-8"))
    metadata["dump_bytes"] = len(replacement_dump)
    metadata["dump_sha256"] = hashlib.sha256(replacement_dump).hexdigest()
    config.backup.write_bytes(replacement_dump)
    config.backup_metadata.write_text(json.dumps(metadata), encoding="utf-8")
    stable_root = tmp_path / "stable-inputs"

    with (
        pytest.raises(restore_drill.DrillError, match="identity changed before stable copy"),
        restore_drill._stable_restore_inputs(config, root=stable_root),
    ):
        pytest.fail("replacement inputs must never reach execution")

    assert stable_root.is_dir()
    assert tuple(stable_root.iterdir()) == ()


def test_postgres_container_user_can_read_the_stable_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = os.getenv("AC_REQUIRE_RESTORE_INPUT_DOCKER_TEST") == "1"
    root_helper = os.getenv("AC_RESTORE_ROOT_HELPER") == "1"
    get_effective_user_id = getattr(os, "geteuid", None)
    running_as_root = bool(callable(get_effective_user_id) and get_effective_user_id() == 0)
    if required and os.name != "posix":
        pytest.fail("the required stable restore-input proof must run on Linux")
    if required and not running_as_root and not root_helper:
        sudo = shutil.which("sudo")
        env_command = shutil.which("env")
        if sudo is None or env_command is None:
            pytest.fail("passwordless sudo is required for the root-ownership proof")
        child = subprocess.run(  # noqa: S603 - exact recursive proof under root
            [
                sudo,
                "--non-interactive",
                env_command,
                "AC_RESTORE_ROOT_HELPER=1",
                "AC_REQUIRE_RESTORE_INPUT_DOCKER_TEST=1",
                "PYTHONDONTWRITEBYTECODE=1",
                "GIT_CONFIG_COUNT=1",
                "GIT_CONFIG_KEY_0=safe.directory",
                f"GIT_CONFIG_VALUE_0={ROOT}",
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"{Path(__file__).resolve()}::test_postgres_container_user_can_read_the_stable_dump",
            ],
            capture_output=True,
            check=False,
            cwd=ROOT,
            text=True,
            timeout=180,
        )
        assert child.returncode == 0, f"stdout:\n{child.stdout}\nstderr:\n{child.stderr}"
        return
    if required and not running_as_root:
        pytest.fail("the required restore-input helper did not obtain root ownership")
    if DOCKER is None:
        if required:
            pytest.fail("Docker is required for the stable restore-input permission proof")
        pytest.skip("Docker CLI is unavailable")
    try:
        daemon = subprocess.run(  # noqa: S603 - fixed read-only Docker probe
            [DOCKER, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if required:
            pytest.fail(f"Docker could not start for the stable input proof: {error}")
        pytest.skip("Docker executable or daemon is unavailable")
    if daemon.returncode != 0:
        if required:
            pytest.fail("Docker daemon is required for the stable restore-input proof")
        pytest.skip("Docker daemon is unavailable")
    image = subprocess.run(  # noqa: S603 - fixed immutable image inspection
        [DOCKER, "image", "inspect", restore_drill.DEFAULT_POSTGRES_IMAGE],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if image.returncode != 0:
        if required:
            pytest.fail("the pinned PostgreSQL image is required for the permission proof")
        pytest.skip("the pinned PostgreSQL image is unavailable")

    def create_exact_labeled_test_volume() -> restore_drill.DisposableTarget:
        for _attempt in range(5):
            candidate = restore_drill._target_for(restore_drill._short_token())
            if restore_drill._docker_inspect_optional("volume", candidate.volume) is not None:
                continue
            creation_error: BaseException | None = None
            try:
                volume_created = subprocess.run(  # noqa: S603 - exact generated disposable volume
                    [
                        DOCKER,
                        "volume",
                        "create",
                        "--label",
                        candidate.label,
                        candidate.volume,
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=30,
                )
                if volume_created.returncode != 0:
                    creation_error = AssertionError(volume_created.stderr)
                else:
                    created_payload = restore_drill._docker_inspect_optional(
                        "volume", candidate.volume
                    )
                    if (
                        created_payload is not None
                        and restore_drill._resource_labels("volume", created_payload).get(
                            restore_drill.LABEL_KEY
                        )
                        == candidate.run_id
                    ):
                        return candidate
            except BaseException as error:
                creation_error = error
            if creation_error is not None:
                try:
                    restore_drill._remove_labeled_resource(
                        "volume", candidate.volume, candidate.run_id
                    )
                except restore_drill.DrillError as cleanup_error:
                    creation_error.add_note(f"cleanup also failed: {cleanup_error}")
                raise creation_error
        pytest.fail("could not create a fresh exact labeled test volume")

    volume_target = create_exact_labeled_test_volume()

    initialization_error: BaseException | None = None
    initialized: subprocess.CompletedProcess[str] | None = None
    cleanup_errors: list[str] = []
    try:
        try:
            initialized = subprocess.run(  # noqa: S603 - bounded generated Docker command
                [
                    DOCKER,
                    *restore_drill._volume_init_command(
                        volume_target,
                        restore_drill.DEFAULT_POSTGRES_IMAGE,
                    ),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
            )
            if initialized.returncode != 0:
                initialization_error = AssertionError(initialized.stderr)
        except BaseException as error:
            initialization_error = error
    finally:
        for kind, name in (
            ("container", volume_target.init_container),
            ("volume", volume_target.volume),
        ):
            try:
                restore_drill._remove_labeled_resource(kind, name, volume_target.run_id)
            except restore_drill.DrillError as error:
                cleanup_errors.append(f"{kind}:{name}: {error}")
    if initialization_error is not None:
        for cleanup_error in cleanup_errors:
            initialization_error.add_note(f"cleanup also failed: {cleanup_error}")
        raise initialization_error
    assert not cleanup_errors, "; ".join(cleanup_errors)
    assert initialized is not None

    if not running_as_root:
        _allow_test_owned_stable_inputs(monkeypatch)
    config = _config(tmp_path, execute=True)
    stable_root = tmp_path / "stable-inputs"
    with restore_drill._stable_restore_inputs(config, root=stable_root) as stable_config:
        if required:
            assert stable_root.stat().st_uid == 0
            assert stable_config.backup.stat().st_uid == 0
            assert stable_config.backup_metadata.stat().st_uid == 0
        command = [
            DOCKER,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--user",
            "999:999",
            "--group-add",
            str(stable_config.backup.stat().st_gid),
            "--security-opt",
            "no-new-privileges:true",
            "--cap-drop",
            "ALL",
            "--mount",
            (f"type=bind,source={stable_config.backup},destination=/restore/backup.dump,readonly"),
            "--entrypoint",
            "/bin/sh",
            restore_drill.DEFAULT_POSTGRES_IMAGE,
            "-euc",
            '[ "$(head -c 5 /restore/backup.dump)" = PGDMP ]',
        ]
        completed = subprocess.run(  # noqa: S603 - fully bounded test command
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr


def test_stable_restore_inputs_are_removed_when_execution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_test_owned_stable_inputs(monkeypatch)
    config = _config(tmp_path, execute=True)
    stable_root = tmp_path / "stable-inputs"

    with (
        pytest.raises(RuntimeError, match="simulated execution failure"),
        restore_drill._stable_restore_inputs(config, root=stable_root),
    ):
        raise RuntimeError("simulated execution failure")

    assert stable_root.is_dir()
    assert tuple(stable_root.iterdir()) == ()


def test_stable_input_creation_error_removes_the_generated_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_test_owned_stable_inputs(monkeypatch)
    stable_root = tmp_path / "stable-inputs"
    real_chmod = Path.chmod

    def fail_generated_directory_chmod(path: Path, mode: int) -> None:
        if restore_drill.STABLE_INPUT_DIR_PATTERN.fullmatch(path.name):
            raise OSError("simulated chmod failure")
        real_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", fail_generated_directory_chmod)

    with pytest.raises(OSError, match="simulated chmod failure"):
        restore_drill._create_stable_input_dir(stable_root)

    assert stable_root.is_dir()
    assert tuple(stable_root.iterdir()) == ()


def test_stable_input_creation_window_ignores_then_restores_cleanup_signals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_test_owned_stable_inputs(monkeypatch)
    config = _config(tmp_path, execute=True)
    stable_root = tmp_path / "stable-inputs"
    previous_handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    observed_during_creation: list[bool] = []
    real_create = restore_drill._create_stable_input_dir

    def observe_create(root: Path) -> Path:
        observed_during_creation.extend(
            signal.getsignal(signum) == signal.SIG_IGN for signum in (signal.SIGINT, signal.SIGTERM)
        )
        return real_create(root)

    monkeypatch.setattr(restore_drill, "_create_stable_input_dir", observe_create)

    with restore_drill._stable_restore_inputs(config, root=stable_root):
        assert all(
            signal.getsignal(signum) == handler for signum, handler in previous_handlers.items()
        )

    assert observed_during_creation == [True, True]
    assert all(signal.getsignal(signum) == handler for signum, handler in previous_handlers.items())


def test_stable_source_copy_rejects_mid_read_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "large.dump"
    source.write_bytes(b"PGDMP" + b"a" * (2 * 1024 * 1024))
    real_read = os.read
    read_count = 0

    def mutating_read(descriptor: int, length: int) -> bytes:
        nonlocal read_count
        chunk = real_read(descriptor, length)
        read_count += 1
        if read_count == 1:
            with source.open("r+b") as mutable:
                mutable.seek(-1, os.SEEK_END)
                mutable.write(b"b")
                mutable.flush()
                os.fsync(mutable.fileno())
        return chunk

    monkeypatch.setattr(restore_drill.os, "read", mutating_read)

    with pytest.raises(restore_drill.DrillError, match="changed during copy"):
        restore_drill._read_stable_source(source, max_bytes=3 * 1024 * 1024)


def test_local_image_preflight_precedes_evidence_directory_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, execute=True)

    def fail_preflight(_target: Any, _config: Any) -> None:
        raise restore_drill.DrillError("application image absent")

    monkeypatch.setattr(restore_drill, "_preflight", fail_preflight)

    with pytest.raises(restore_drill.DrillError, match="application image absent"):
        restore_drill._execute(config)
    assert not config.evidence_dir.exists()


def test_evidence_is_exclusive_atomically_published_and_mode_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_dir = tmp_path / "evidence"
    restore_drill._create_evidence_dir(evidence_dir)
    requested_modes: list[int] = []
    real_open = os.open

    def recording_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if Path(path).name.startswith(".restore-drill-"):
            requested_modes.append(mode)
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", recording_open)
    target = restore_drill._write_evidence(
        evidence_dir,
        {"result": "passed"},
        "0123456789ab",
    )

    assert requested_modes == [0o600]
    assert json.loads(target.read_text(encoding="utf-8")) == {"result": "passed"}
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(restore_drill.DrillError, match="already exists"):
        restore_drill._write_evidence(
            evidence_dir,
            {"result": "replacement"},
            "0123456789ab",
        )
    assert json.loads(target.read_text(encoding="utf-8")) == {"result": "passed"}


def test_held_jobs_are_excluded_from_uncertain_count_and_transition_is_exact() -> None:
    assert "NOT IN ('held', 'succeeded', 'dead_letter')" in (restore_drill.SIDE_EFFECT_COUNTS_QUERY)
    before = restore_drill.SideEffectCounts(
        pending_outbox=2,
        uncertain_external_jobs=3,
        held_outbox=4,
        held_external_jobs=5,
        held_recovery_state=0,
        ready_recovery_state=1,
    )
    after = restore_drill.SideEffectCounts(
        pending_outbox=0,
        uncertain_external_jobs=0,
        held_outbox=6,
        held_external_jobs=8,
        held_recovery_state=1,
        ready_recovery_state=0,
    )
    marker = {"generation": 2, "status": "held", "held_outbox": 2, "held_jobs": 8}

    restore_drill._assert_hold_transition(before, after, marker)
    marker["held_jobs"] = 3
    with pytest.raises(restore_drill.DrillError, match="exact external job transition"):
        restore_drill._assert_hold_transition(before, after, marker)


def test_reconciliation_requires_a_named_bounded_set_and_acknowledgement() -> None:
    args = SimpleNamespace(
        reconcile_job_id=[UUID("00000000-0000-0000-0000-000000000001")],
        reconcile_outbox_event_id=[],
        reconcile_actor_person_id=UUID("00000000-0000-0000-0000-000000000002"),
        reconcile_tenant_id=UUID("00000000-0000-0000-0000-000000000003"),
        reconcile_reason="reviewed",
        acknowledge_reconciliation=False,
    )

    with pytest.raises(restore_drill.DrillError, match="acknowledge-reconciliation"):
        restore_drill._validate_reconciliation_args(args)

    args.acknowledge_reconciliation = True
    restore_drill._validate_reconciliation_args(args)


def test_reconciliation_cannot_be_acknowledged_without_selection() -> None:
    args = SimpleNamespace(
        reconcile_job_id=[],
        reconcile_outbox_event_id=[],
        reconcile_actor_person_id=None,
        reconcile_tenant_id=None,
        reconcile_reason=None,
        acknowledge_reconciliation=True,
    )

    with pytest.raises(restore_drill.DrillError, match="explicit selected set"):
        restore_drill._validate_reconciliation_args(args)


def test_dry_run_plan_is_non_mutating_and_contains_rpo_inputs(tmp_path: Path) -> None:
    config = _config(tmp_path)

    plan = restore_drill._dry_run_plan(config)

    assert plan["mode"] == "dry-run"
    assert plan["backup_sha256"]
    assert plan["external_connections"] == []
    assert plan["application_image"] == APPLICATION_IMAGE
    assert not config.evidence_dir.exists()


@pytest.mark.skipif(
    os.getenv("AC_RUN_RESTORE_DRILL_INTEGRATION") != "1",
    reason="set AC_RUN_RESTORE_DRILL_INTEGRATION=1 with an approved dump to opt in",
)
def test_restore_drill_live_opt_in() -> None:
    backup = os.getenv("AC_RESTORE_DRILL_BACKUP")
    metadata = os.getenv("AC_RESTORE_DRILL_METADATA")
    evidence_dir = os.getenv("AC_RESTORE_DRILL_EVIDENCE_DIR")
    application_image = os.getenv("AC_RESTORE_DRILL_APPLICATION_IMAGE")
    environment = os.getenv("AC_RESTORE_DRILL_ENVIRONMENT", "staging")
    if not backup or not metadata or not evidence_dir or not application_image:
        pytest.skip(
            "AC_RESTORE_DRILL_BACKUP, AC_RESTORE_DRILL_METADATA, "
            "AC_RESTORE_DRILL_EVIDENCE_DIR, and AC_RESTORE_DRILL_APPLICATION_IMAGE are required"
        )
    completed = subprocess.run(  # noqa: S603 - explicit opt-in repository script only
        [
            sys.executable,
            str(SCRIPT),
            "--environment",
            environment,
            "--backup",
            backup,
            "--backup-metadata",
            metadata,
            "--evidence-dir",
            evidence_dir,
            "--application-image",
            application_image,
            "--execute",
            "--acknowledge-isolated-target",
        ],
        check=False,
        timeout=RESTORE_DRILL_TEST_TIMEOUT_SECONDS,
    )
    assert completed.returncode == 0


RESTORE_DRILL_TEST_TIMEOUT_SECONDS = 75 * 60

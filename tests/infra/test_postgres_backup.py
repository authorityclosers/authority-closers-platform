from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import time
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "infra" / "vps-foundation"
SCRIPT = FOUNDATION / "scripts" / "ac-postgres-backup.py"

spec = importlib.util.spec_from_file_location("ac_postgres_backup", SCRIPT)
assert spec and spec.loader
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)


def _write_manifest(release: Path) -> None:
    manifest = release / "RELEASE-FILES.sha256"
    files = sorted(path for path in release.rglob("*") if path.is_file() and path != manifest)
    manifest.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"./{path.relative_to(release).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )


def _write_release(root: Path, environment: str = "staging") -> Path:
    if environment not in backup.ENVIRONMENTS:
        raise ValueError(f"Unsupported fixture environment: {environment}")

    release = root / "srv" / "authority-closers" / "application" / "releases" / ("a" * 40)
    (release / "environments").mkdir(parents=True)
    (release / "compose.yaml").write_text("name: ${AC_COMPOSE_PROJECT}\n", encoding="utf-8")
    (release / "release-images.env").write_text(
        "AC_RELEASE_ID=" + "a" * 40 + "\n", encoding="utf-8"
    )
    source_profile = ROOT / "infra" / "application" / "environments" / f"{environment}.env"
    (release / "environments" / f"{environment}.env").write_text(
        source_profile.read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write_manifest(release)
    state = root / "srv" / "authority-closers" / "state" / "application" / environment
    state.mkdir(parents=True)
    current = root / "srv" / "authority-closers" / "application" / f"current-{environment}"
    try:
        current.symlink_to(release, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"fixture symlinks are unavailable: {exc}")
    return release


def test_path_resolution_uses_exact_current_release_profile_and_skips_absent_production(
    tmp_path: Path,
) -> None:
    release = _write_release(tmp_path)

    target = backup.resolve_application_release("staging", host_root=tmp_path)
    assert target is not None
    assert target.release_dir == release
    assert target.compose_project == "ac-application-staging"
    assert (
        backup.resolve_application_release("production", host_root=tmp_path, allow_missing=True)
        is None
    )


def test_path_resolution_accepts_the_held_fake_production_profile(tmp_path: Path) -> None:
    release = _write_release(tmp_path, environment="production")

    target = backup.resolve_application_release("production", host_root=tmp_path)

    assert target is not None
    assert target.release_dir == release
    assert target.compose_project == "ac-application-production"


@pytest.mark.parametrize(
    ("reviewed", "stale"),
    (
        ("AC_EXTERNAL_SIDE_EFFECTS_HOLD=false", "AC_EXTERNAL_SIDE_EFFECTS_HOLD=true"),
        ("AC_EMAIL_PROVIDER=resend", "AC_EMAIL_PROVIDER=fake"),
    ),
)
def test_path_resolution_rejects_a_stale_staging_provider_profile(
    tmp_path: Path, reviewed: str, stale: str
) -> None:
    release = _write_release(tmp_path)
    profile = release / "environments" / "staging.env"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(reviewed, stale), encoding="utf-8"
    )
    _write_manifest(release)

    with pytest.raises(backup.BackupError, match="profile is not exact"):
        backup.resolve_application_release("staging", host_root=tmp_path)


def test_projection_rejects_a_boundary_that_would_exceed_the_envelope() -> None:
    policy = backup.read_policy(FOUNDATION / "config" / "r2" / "free-tier-policy.conf")
    projection = backup.projected_logical_bytes(policy)
    assert projection == 8_388_608 * 336 * 2

    unsafe = dict(policy)
    unsafe["R2_MAX_STANDARD_BYTES"] = projection - 1
    with pytest.raises(backup.BackupError):
        backup.projected_logical_bytes(unsafe)


def test_lock_files_are_hardened_through_the_open_descriptor() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | no_follow" in source
    assert "dir_fd=directory_fd" in source
    assert "os.fchmod(lock_fd, 0o640)" in source
    assert "os.fchown(lock_fd, expected_uid, expected_gid)" in source
    assert "lock_file.chmod" not in source
    assert "lock_path.chown(" not in source
    for path_call in (
        "path.chown(",
        "temporary_dir.chown(",
        "metadata_path_tmp.chown(",
        "temporary_path.chown(",
    ):
        assert path_call not in source
    assert source.count("os.chown(") == 4
    assert source.count("follow_symlinks=False") >= 5


def test_every_restic_entrypoint_uses_the_same_private_repository_lock() -> None:
    scripts = (
        "ac-restic-backup-inner",
        "ac-restic-init-inner",
        "ac-restic-restore-check-inner",
        "ac-restic-postgres-backup-inner",
    )
    for name in scripts:
        source = (FOUNDATION / "scripts" / name).read_text(encoding="utf-8")
        assert "restic_lock_dir='/run/lock/authority-closers'" in source
        assert 'restic_lock_file="$restic_lock_dir/ac-restic-repository.lock"' in source
        assert ">>/run/lock/ac-restic-repository.lock" not in source
        assert "stat --dereference --format='%u:%g:%a:%h' -- /proc/self/fd/9" in source
        assert "0:$acops_gid:640:1" in source


@pytest.mark.skipif(os.name != "posix", reason="Bash syntax proof runs on POSIX CI")
@pytest.mark.parametrize(
    "name",
    (
        "ac-restic-backup-inner",
        "ac-restic-init-inner",
        "ac-restic-restore-check-inner",
        "ac-restic-postgres-backup-inner",
    ),
)
def test_restic_entrypoint_has_valid_bash_syntax(name: str) -> None:
    bash = Path("/usr/bin/bash")
    assert bash.is_file()
    result = subprocess.run(  # noqa: S603 - fixed interpreter and parameterized trusted fixture
        [str(bash), "-n", str(FOUNDATION / "scripts" / name)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(backup.fcntl is None, reason="POSIX file locks are unavailable")
def test_lock_contexts_create_exact_mode_files_on_posix(tmp_path: Path) -> None:
    with backup.environment_lock("staging", tmp_path):
        lock_root = tmp_path / "run" / "lock" / "authority-closers"
        environment_path = lock_root / "ac-postgres-backup-staging.lock"
        assert lock_root.stat().st_mode & 0o777 == 0o750
        assert environment_path.stat().st_mode & 0o777 == 0o640

    with backup.repository_lock(tmp_path):
        repository_path = lock_root / "ac-restic-repository.lock"
        assert repository_path.stat().st_mode & 0o777 == 0o640


@pytest.mark.skipif(backup.fcntl is None, reason="POSIX file locks are unavailable")
def test_lock_context_rejects_a_precreated_private_directory_symlink(tmp_path: Path) -> None:
    lock_parent = tmp_path / "run" / "lock"
    attacker_directory = tmp_path / "attacker"
    lock_parent.mkdir(parents=True)
    attacker_directory.mkdir()
    try:
        (lock_parent / "authority-closers").symlink_to(attacker_directory, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"fixture symlinks are unavailable: {exc}")

    with pytest.raises(backup.BackupError), backup.environment_lock("staging", tmp_path):
        pass


def test_dump_command_is_custom_format_ac_backup_and_does_not_contain_a_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = backup.ApplicationTarget(
        environment="staging",
        current_link=tmp_path / "current-staging",
        release_dir=tmp_path / ("a" * 40),
        profile_file=tmp_path / "staging.env",
        images_file=tmp_path / "release-images.env",
        state_root=tmp_path / "state",
        compose_project="ac-application-staging",
        secret_environment="staging",  # noqa: S106
    )
    snapshot_id = "00000003-0000001B-1"
    command = " ".join(backup.dump_command(target, snapshot_id))
    assert "-U ac_backup" in command
    assert "--format=custom" in command
    assert "--create" in command
    assert f"--snapshot={snapshot_id}" in command
    assert 'PGPASSWORD="$AC_DB_BACKUP_PASSWORD"' in command
    assert "staging-runtime-password" not in command

    monkeypatch.setenv(
        "AC_DB_BACKUP_PASSWORD",
        "fixture-secret-that-must-not-cross-the-wrapper",  # noqa: S106
    )
    monkeypatch.setenv(
        "AC_DATABASE_URL",
        "postgresql://arbitrary-dsn-must-not-cross-the-wrapper",  # noqa: S106
    )
    monkeypatch.setenv("AC_TRUSTED_PROXY_ADDRESSES", "9.9.9.9")
    assert "AC_DB_BACKUP_PASSWORD" not in backup.compose_environment(target)
    assert "AC_DATABASE_URL" not in backup.compose_environment(target)
    assert "AC_TRUSTED_PROXY_ADDRESSES" not in backup.compose_environment(target)


def test_source_parity_query_is_fixed_to_the_canonical_table_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = backup.ApplicationTarget(
        environment="staging",
        current_link=tmp_path / "current-staging",
        release_dir=tmp_path / ("a" * 40),
        profile_file=tmp_path / "staging.env",
        images_file=tmp_path / "release-images.env",
        state_root=tmp_path / "state",
        compose_project="ac-application-staging",
        secret_environment="staging",  # noqa: S106
    )
    snapshot_id = "00000003-0000001B-1"
    command_parts = backup.parity_command(target, snapshot_id)
    command = " ".join(command_parts)
    assert "psql --no-password" in command
    assert "--no-psqlrc" in command
    assert "--set=ON_ERROR_STOP=1" in command
    assert "-qAt" in command
    assert 'PGPASSWORD="$AC_DB_BACKUP_PASSWORD"' in command
    assert all(f'FROM "{table}"' in command for table in backup.PARITY_TABLES)
    assert "fixture-secret" not in command
    assert command_parts[-2] == "--"
    assert command_parts[-1].startswith("BEGIN ISOLATION LEVEL REPEATABLE READ")
    assert f"SET TRANSACTION SNAPSHOT '{snapshot_id}'" in command_parts[-1]
    assert "UNION ALL" in command_parts[-1]

    output = "\n".join(f"{table}|0" for table in backup.PARITY_TABLES)
    monkeypatch.setattr(
        backup,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )
    assert backup.source_row_counts(target, snapshot_id) == {
        table: 0 for table in backup.PARITY_TABLES
    }

    tagged = f"BEGIN\n{output}\nCOMMIT"
    monkeypatch.setattr(
        backup,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=tagged),
    )
    with pytest.raises(backup.BackupError, match="unsafe result"):
        backup.source_row_counts(target, snapshot_id)

    incomplete = output.rsplit("\n", 1)[0]
    monkeypatch.setattr(
        backup,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=incomplete),
    )
    with pytest.raises(backup.BackupError, match="incomplete"):
        backup.source_row_counts(target, snapshot_id)


def test_exported_snapshot_holder_rolls_back_and_fails_closed_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStdin:
        def __init__(self) -> None:
            self.data = b""
            self.closed = False

        def write(self, data: bytes) -> None:
            self.data += data

        def flush(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    class FakeProcess:
        def __init__(self, *, timeout: bool) -> None:
            self.stdin = FakeStdin()
            self.stdout = type(
                "FakeStdout",
                (),
                {"readline": lambda _self: b"00000003-0000001B-1\n"},
            )()
            self.returncode: int | None = None
            self.timeout = timeout

        def poll(self) -> None:
            return None

        def wait(self, *, timeout: int) -> int:
            assert timeout == backup.SNAPSHOT_HOLDER_ROLLBACK_TIMEOUT_SECONDS
            if self.timeout:
                raise subprocess.TimeoutExpired(["psql"], timeout)
            self.returncode = 0
            return 0

    start_process = FakeProcess(timeout=False)
    monkeypatch.setattr(backup, "snapshot_holder_command", lambda _target: ["snapshot-holder"])
    monkeypatch.setattr(backup, "compose_environment", lambda _target: {})
    monkeypatch.setattr(backup.subprocess, "Popen", lambda *_args, **_kwargs: start_process)
    started_holder = backup.start_exported_snapshot_holder(object())
    assert start_process.stdin.data == backup.SNAPSHOT_HOLDER_START_SQL
    assert started_holder.snapshot_id == "00000003-0000001B-1"
    started_holder.close()

    clean_process = FakeProcess(timeout=False)
    clean_holder = backup.ExportedSnapshotHolder(
        clean_process, "00000003-0000001B-1", time.monotonic()
    )
    clean_holder.close()
    assert clean_process.stdin.closed
    assert clean_process.stdin.data == b"ROLLBACK;\n\\q\n"

    timed_out_process = FakeProcess(timeout=True)
    terminated: list[object] = []
    monkeypatch.setattr(backup, "terminate_process", terminated.append)
    timed_out_holder = backup.ExportedSnapshotHolder(
        timed_out_process, "00000003-0000001B-1", time.monotonic()
    )
    with pytest.raises(backup.BackupError, match="rollback timed out"):
        timed_out_holder.close()
    assert terminated == [timed_out_process]


def test_exported_snapshot_identity_is_validated_before_command_binding(
    tmp_path: Path,
) -> None:
    target = backup.ApplicationTarget(
        environment="staging",
        current_link=tmp_path / "current-staging",
        release_dir=tmp_path / ("a" * 40),
        profile_file=tmp_path / "staging.env",
        images_file=tmp_path / "release-images.env",
        state_root=tmp_path / "state",
        compose_project="ac-application-staging",
        secret_environment="staging",  # noqa: S106
    )
    for builder in (backup.dump_command, backup.parity_command):
        with pytest.raises(backup.BackupError, match="snapshot identity"):
            builder(target, "snapshot;secret")


def test_publish_retention_happens_after_upload_and_failed_upload_keeps_verified_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backup, "is_root_owned", lambda _path: True)
    logical_dir = tmp_path / "staging" / "logical"
    logical_dir.mkdir(parents=True)
    old_capture = logical_dir / "20260101T000000.000000Z-100-staging"
    capture = logical_dir / "20260101T001500.000000Z-101-staging"
    old_capture.mkdir()
    capture.mkdir()
    old_dump = old_capture / "backup.dump"
    old_metadata = old_capture / "metadata.json"
    dump = capture / "backup.dump"
    metadata = capture / "metadata.json"
    for path in (dump, metadata, old_dump, old_metadata):
        path.write_text("verified", encoding="utf-8")

    def failed_upload(*_args) -> None:
        raise backup.BackupError("upload failed")

    with pytest.raises(backup.BackupError):
        backup.publish_snapshot(
            dump,
            metadata,
            "staging",
            1,
            capture_only=False,
            uploader=failed_upload,
            keep_points=1,
        )
    assert dump.exists() and metadata.exists()
    assert not old_capture.exists()

    backup.publish_snapshot(
        dump,
        metadata,
        "staging",
        1,
        capture_only=False,
        uploader=lambda *_args: None,
        keep_points=1,
    )
    assert dump.exists() and metadata.exists()
    assert not old_capture.exists()


def test_timer_and_unit_are_persistent_bounded_and_hardened() -> None:
    timer = ConfigParser()
    timer.read(FOUNDATION / "config" / "systemd" / "ac-postgres-backup.timer")
    assert timer["Timer"]["OnCalendar"] == "*:0/5"
    assert timer["Timer"]["Persistent"].lower() == "true"
    assert timer["Timer"]["RandomizedDelaySec"] == "30s"
    assert timer["Timer"]["Unit"] == "ac-postgres-backup.service"

    service = (FOUNDATION / "config" / "systemd" / "ac-postgres-backup.service").read_text(
        encoding="utf-8"
    )
    for marker in (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "RestrictAddressFamilies=AF_INET AF_UNIX",
        "CapabilityBoundingSet=",
        "ReadWritePaths=/srv/authority-closers/backups/application /run/lock",
        "TimeoutStartSec=60min",
        "TimeoutStopSec=30s",
        "Environment=AC_IPV4_ONLY=1",
        "ExecStart=/usr/local/sbin/ac-postgres-backup",
        "Nice=10",
        "IOSchedulingPriority=7",
    ):
        assert marker in service

    assert "--environment staging" not in service
    assert (
        backup.worst_case_two_environment_backup_seconds() <= backup.BACKUP_SERVICE_TIMEOUT_SECONDS
    )


def test_r2_guard_retry_and_transient_unit_bounds_are_aligned() -> None:
    assert backup.R2_GUARD_HTTP_CALLS == 2
    assert backup.R2_GUARD_UNIT_TIMEOUT_SECONDS == 180
    assert backup.R2_GUARD_STOP_TIMEOUT_SECONDS == 30
    assert backup.R2_GUARD_CLIENT_GRACE_SECONDS == 30
    assert backup.R2_GUARD_CLIENT_TIMEOUT_SECONDS == 240

    wrapper = (FOUNDATION / "scripts" / "ac-r2-usage-guard").read_text(encoding="utf-8")
    assert "--retry-max-time 75" in (FOUNDATION / "scripts" / "r2-usage-guard.sh").read_text(
        encoding="utf-8"
    )
    assert "TimeoutStartSec=${R2_GUARD_UNIT_TIMEOUT_SECONDS}s" in wrapper
    assert "TimeoutStopSec=${R2_GUARD_STOP_TIMEOUT_SECONDS}s" in wrapper
    assert "trap cancel_transient_unit EXIT INT TERM" in wrapper
    assert 'systemctl stop "$transient_unit"' in wrapper

    guard_service = (FOUNDATION / "config" / "systemd" / "ac-r2-usage-guard.service").read_text(
        encoding="utf-8"
    )
    assert "TimeoutStartSec=180s" in guard_service
    assert "TimeoutStopSec=30s" in guard_service


def test_foundation_restic_units_have_wall_clock_and_cleanup_bounds() -> None:
    expected = {
        "ac-restic-backup.service": "TimeoutStartSec=90min",
        "ac-restic-restore-check.service": "TimeoutStartSec=75min",
    }
    for unit_name, start_timeout in expected.items():
        service = (FOUNDATION / "config" / "systemd" / unit_name).read_text(encoding="utf-8")
        assert start_timeout in service
        assert "TimeoutStopSec=30s" in service
        assert "KillMode=mixed" in service

    interval_seconds = 5 * 60
    jitter_seconds = 30
    assert (
        interval_seconds
        + jitter_seconds
        + backup.PG_DUMP_TIMEOUT_SECONDS
        + backup.RESTIC_UPLOAD_TIMEOUT_SECONDS
        <= 15 * 60
    )


def test_database_backup_continues_when_non_database_services_are_unhealthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = backup.ApplicationTarget(
        environment="staging",
        current_link=tmp_path / "current-staging",
        release_dir=tmp_path / ("a" * 40),
        profile_file=tmp_path / "staging.env",
        images_file=tmp_path / "release-images.env",
        state_root=tmp_path / "state",
        compose_project="ac-application-staging",
        secret_environment="staging",  # noqa: S106
    )
    compose_calls: list[list[str]] = []

    def fake_checked(command: list[str], **_kwargs: object) -> SimpleNamespace:
        compose_calls.append(command)
        return SimpleNamespace(stdout="a" * 12)

    monkeypatch.setattr(backup, "run_checked", fake_checked)
    monkeypatch.setattr(
        backup.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="healthy"),
    )

    backup.assert_healthy(target)

    assert len(compose_calls) == 1
    assert compose_calls[0][-3:] == ["ps", "-q", "postgres"]


def test_local_ring_refuses_incomplete_backup_pairs(tmp_path: Path) -> None:
    logical_dir = tmp_path / "staging" / "logical"
    logical_dir.mkdir(parents=True)
    capture = logical_dir / "20260101T000000.000000Z-100-staging"
    capture.mkdir()
    (capture / "backup.dump").write_text("verified", encoding="utf-8")

    with pytest.raises(backup.BackupError, match="incomplete pair"):
        backup.prune_local_ring(logical_dir, 1)


def test_local_ring_recovers_atomic_capture_and_prune_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backup, "is_root_owned", lambda _path: True)
    stale_capture = tmp_path / ".staging-abcd.capture.tmp"
    stale_capture.mkdir()
    (stale_capture / "backup.dump").write_text("partial", encoding="utf-8")
    stale_prune = tmp_path / ".prune-20260101T000000.000000Z-100-staging"
    stale_prune.mkdir()
    for name in ("backup.dump", "metadata.json"):
        (stale_prune / name).write_text("verified", encoding="utf-8")

    backup.remove_stale_temporaries(tmp_path, "staging")

    assert not stale_capture.exists()
    assert not stale_prune.exists()


def test_capture_cleanup_refuses_a_non_root_owned_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = tmp_path / ".staging-abcd.capture.tmp"
    capture.mkdir()
    (capture / "backup.dump").write_text("partial", encoding="utf-8")
    monkeypatch.setattr(backup, "is_root_owned", lambda _path: False)

    with pytest.raises(backup.BackupError, match="capture directory is unsafe"):
        backup.remove_capture_directory(capture, temporary=True)

    assert capture.exists()
    assert (capture / "backup.dump").exists()


def test_logical_restic_retention_groups_changing_paths_by_tag() -> None:
    retention = (FOUNDATION / "scripts" / "ac-restic-backup-inner").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")

    assert "--tag authority-closers-postgres-logical" in retention
    assert "--group-by host,tags" in retention
    assert "--keep-within 27h" in retention
    assert "os.fsync(destination.fileno())" in source
    command = backup.upload_command(
        Path("/srv/authority-closers/backups/application/staging/logical/test.dump"),
        Path("/srv/authority-closers/backups/application/staging/logical/test.json"),
        "staging",
    )
    assert command[:5] == [
        "timeout",
        "--foreground",
        f"--kill-after={backup.OPERATION_KILL_AFTER_SECONDS}s",
        f"{backup.RESTIC_UPLOAD_TIMEOUT_SECONDS}s",
        backup.RESTIC_LOGICAL_BACKUP,
    ]


def test_every_operational_script_and_unit_is_in_the_exact_install_manifest() -> None:
    manifest = {
        row.split("\t")[1]
        for row in (FOUNDATION / "config" / "release" / "install-manifest.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
        if row and not row.startswith("#")
    }
    for source in (FOUNDATION / "scripts").glob("ac-*"):
        assert str(source.relative_to(FOUNDATION)).replace(os.sep, "/") in manifest
    for source in (FOUNDATION / "config" / "systemd").glob("*"):
        assert str(source.relative_to(FOUNDATION)).replace(os.sep, "/") in manifest

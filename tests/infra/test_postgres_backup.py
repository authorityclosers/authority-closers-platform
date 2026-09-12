from __future__ import annotations

import errno
import hashlib
import importlib.util
import os
import subprocess
import sys
import time
from configparser import ConfigParser
from contextlib import nullcontext
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
        "AC_RELEASE_ID=" + "a" * 40 + "\nAC_MIGRATION_HEAD=20260904_0018\n", encoding="utf-8"
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


@pytest.mark.parametrize(("hold", "provider"), [("true", "fake"), ("false", "resend")])
def test_path_resolution_accepts_exact_production_activation_pairs(
    tmp_path: Path,
    hold: str,
    provider: str,
) -> None:
    release = _write_release(tmp_path, environment="production")
    profile = release / "environments" / "production.env"
    profile.write_text(
        profile.read_text(encoding="utf-8")
        .replace("AC_EXTERNAL_SIDE_EFFECTS_HOLD=false", f"AC_EXTERNAL_SIDE_EFFECTS_HOLD={hold}")
        .replace("AC_EMAIL_PROVIDER=resend", f"AC_EMAIL_PROVIDER={provider}"),
        encoding="utf-8",
    )
    _write_manifest(release)

    target = backup.resolve_application_release("production", host_root=tmp_path)

    assert target is not None
    assert target.release_dir == release
    assert target.compose_project == "ac-application-production"


@pytest.mark.parametrize(
    ("hold", "provider"),
    [("true", "resend"), ("false", "fake"), ("false", "smtp"), ("maybe", "resend")],
)
def test_path_resolution_rejects_mixed_or_unreviewed_production_activation_pairs(
    tmp_path: Path,
    hold: str,
    provider: str,
) -> None:
    release = _write_release(tmp_path, environment="production")
    profile = release / "environments" / "production.env"
    profile.write_text(
        profile.read_text(encoding="utf-8")
        .replace("AC_EXTERNAL_SIDE_EFFECTS_HOLD=false", f"AC_EXTERNAL_SIDE_EFFECTS_HOLD={hold}")
        .replace("AC_EMAIL_PROVIDER=resend", f"AC_EMAIL_PROVIDER={provider}"),
        encoding="utf-8",
    )
    _write_manifest(release)

    with pytest.raises(backup.BackupError, match="profile is not exact"):
        backup.resolve_application_release("production", host_root=tmp_path)


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


def test_foundation_restore_reads_require_r2_admission_under_the_repository_lock() -> None:
    source = (FOUNDATION / "scripts" / "ac-restic-restore-check-inner").read_text(encoding="utf-8")
    guard = "/usr/local/libexec/authority-closers/r2-usage-guard"
    assert source.count(guard) == 1
    assert source.index('exec 9>>"$restic_lock_file"') < source.index("# Repository lock acquired.")
    assert source.index("# Repository lock acquired.") < source.index(guard)
    assert source.index(guard) < source.index("$(restic snapshots ")
    assert (
        f"if ! {guard} >/dev/null 2>&1; then\n"
        "  printf 'AC_BACKUP_FAILURE=r2_quota_paused\\n' >&2\n"
        "  exit 1\nfi"
    ) in source
    assert "restic snapshots --tag authority-closers-foundation --latest 1 --json" in source
    assert 'restic restore "$snapshot_id" --target "$restore_dir"' in source
    assert "restic check --read-data-subset=1/20" in source
    policy = backup.read_policy(FOUNDATION / "config" / "r2" / "free-tier-policy.conf")
    assert policy["R2_MAX_CLASS_B_MONTH"] == 7_000_000


@pytest.mark.parametrize("guard_status", [0, 17])
def test_foundation_restore_admission_executes_before_any_restic_call(guard_status: int) -> None:
    bash = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe"
        if os.name == "nt"
        else Path("/usr/bin/bash")
    )
    if not bash.is_file():
        pytest.skip("Bash is unavailable for the synthetic admission proof")
    source = (FOUNDATION / "scripts" / "ac-restic-restore-check-inner").read_text(encoding="utf-8")
    block = source.split("# Repository lock acquired.\n", 1)[1].split("\nsnapshot_count=", 1)[0]
    block = block.replace("/usr/local/libexec/authority-closers/r2-usage-guard", "synthetic_guard")
    # Only admission and the first read run here. POSIX tests separately exercise
    # the actual fd9 lock. Descriptor 3 records synthetic calls past redirection.
    harness = r"""
set -euo pipefail
exec 3>&1
synthetic_guard_status="$1"
AC_FOUNDATION_RPO_TARGET_SECONDS=86400
AC_FOUNDATION_RESTORE_TARGET_SECONDS=14400
synthetic_guard() {
  printf 'GUARD_CALL\n' >&3
  printf 'synthetic-private-guard-output\n'
  printf 'synthetic-private-guard-error\n' >&2
  return "$synthetic_guard_status"
}
restic() {
  printf 'RESTIC_CALL:%s\n' "$*" >&3
  printf '[]\n'
}
"""
    result = subprocess.run(  # noqa: S603 - source block calls synthetic functions only
        [str(bash), "-c", harness + block, "proof", str(guard_status)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == (0 if guard_status == 0 else 1)
    expected_calls = ["GUARD_CALL"]
    if guard_status == 0:
        expected_calls.append(
            "RESTIC_CALL:snapshots --tag authority-closers-foundation --latest 1 --json"
        )
    assert result.stdout.splitlines() == expected_calls
    assert result.stderr == ("" if guard_status == 0 else "AC_BACKUP_FAILURE=r2_quota_paused\n")


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
        migration_head="20260904_0018",
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
        migration_head="20260904_0018",
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

    output = "__migration_head__|20260904_0018\n" + "\n".join(
        f"{table}|0" for table in backup.PARITY_TABLES
    )
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
        migration_head="20260904_0018",
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


@pytest.fixture
def local_backup_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Exercise run/publish/retention with isolated local pairs and no live services."""
    events: list[str] = []
    targets = [SimpleNamespace(environment="staging"), SimpleNamespace(environment="production")]
    policy = backup.read_policy(FOUNDATION / "config/r2/free-tier-policy.conf")
    policy["R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"] = 2
    monkeypatch.setenv("AC_POSTGRES_BACKUP_HOST_ROOT", str(tmp_path))
    monkeypatch.setattr(backup.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(backup, "read_policy", lambda _path: policy)
    monkeypatch.setattr(backup, "resolve_targets", lambda **_kwargs: targets)
    monkeypatch.setattr(backup, "assert_healthy", lambda target: events.append(target.environment))
    monkeypatch.setattr(backup, "is_root_owned", lambda _path: True)
    monkeypatch.setattr(backup, "fsync_directory", lambda _path: None)
    monkeypatch.setattr(
        backup, "prepare_directory", lambda path: path.mkdir(parents=True, exist_ok=True)
    )
    monkeypatch.setattr(backup, "environment_lock", lambda *_args: nullcontext())
    monkeypatch.setattr(backup, "repository_lock", lambda *_args: nullcontext(17))
    sequence = [0]

    def capture(target, logical_dir, max_bytes):
        assert max_bytes == 8 * 1024 * 1024
        sequence[0] += 1
        capture_dir = logical_dir / (f"20260911T000000.{sequence[0]:06d}Z-101-{target.environment}")
        capture_dir.mkdir()
        dump, metadata = capture_dir / "backup.dump", capture_dir / "metadata.json"
        dump.write_bytes(b"verified synthetic dump")
        metadata.write_text("{}", encoding="utf-8")
        events.append(f"capture:{target.environment}")
        return dump, metadata, {}

    def upload(_dump, _metadata, environment, _projected, *, repository_lock_fd):
        assert repository_lock_fd == 17
        events.append(f"upload:{environment}")

    monkeypatch.setattr(backup, "capture_dump", capture)
    monkeypatch.setattr(backup, "upload_dump", upload)
    monkeypatch.setattr(backup, "run_r2_guard", lambda _projected: events.append("guard"))
    return SimpleNamespace(
        root=tmp_path,
        events=events,
        targets=targets,
        policy=policy,
        capture=capture,
        sequence=sequence,
        args=SimpleNamespace(environment=None, capture_only=False, dry_run=False),
    )


def test_capture_only_keeps_pairs_without_any_offsite_operation(local_backup_run) -> None:
    run = local_backup_run
    run.args.capture_only = True
    backup.run(run.args)
    assert "guard" not in run.events
    assert not any(event.startswith("upload:") for event in run.events)
    assert len(list(run.root.rglob("backup.dump"))) == 2
    assert len(list(run.root.rglob("metadata.json"))) == 2


@pytest.mark.parametrize("capture_only", [False, True])
def test_dry_run_never_captures_or_prunes(local_backup_run, capture_only: bool) -> None:
    run = local_backup_run
    run.args.dry_run = True
    run.args.capture_only = capture_only
    backup.run(run.args)
    assert run.events == ["staging", "production"] + ([] if capture_only else ["guard"])
    assert not list(run.root.iterdir())


def test_quota_failure_retains_both_local_pairs_and_remains_failed(
    local_backup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = local_backup_run

    def reject(_projected):
        run.events.append("guard:rejected")
        raise backup.BackupError("R2 usage is not safe.")

    monkeypatch.setattr(backup, "run_r2_guard", reject)
    for _attempt in range(4):
        with pytest.raises(backup.BackupError, match="staging, production") as failure:
            backup.run(run.args)
        assert "verified local pair was retained" in str(failure.value)
    assert run.events[2:6] == [
        "capture:staging",
        "guard:rejected",
        "capture:production",
        "guard:rejected",
    ]
    assert not any(event.startswith("upload:") for event in run.events)
    # Four repeated failures still retain exactly two complete pairs per environment.
    assert len(list(run.root.rglob("backup.dump"))) == 4
    assert len(list(run.root.rglob("metadata.json"))) == 4
    assert run.sequence[0] == 8


def test_successful_offsite_write_follows_capture_and_guard(local_backup_run) -> None:
    run = local_backup_run
    backup.run(run.args)
    assert run.events == [
        "staging",
        "production",
        "capture:staging",
        "guard",
        "upload:staging",
        "capture:production",
        "guard",
        "upload:production",
    ]


def test_unsafe_ring_blocks_capture_before_any_offsite_call(
    local_backup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = local_backup_run
    run.targets.pop()
    run.args.capture_only = True
    backup.run(run.args)
    metadata = next(run.root.rglob("metadata.json"))
    metadata.unlink()
    run.events.clear()
    with pytest.raises(backup.BackupError, match="incomplete pair"):
        backup.run(run.args)
    assert run.events == ["staging"]
    assert run.sequence[0] == 1
    assert metadata.parent.exists()


def test_failed_retention_prevents_repeated_capture_growth(
    local_backup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = local_backup_run
    run.targets.pop()
    run.args.capture_only = True
    backup.run(run.args)
    backup.run(run.args)

    def failed_remove(*_args, **_kwargs):
        raise OSError("synthetic-sensitive-filesystem-detail")

    def reject(_projected):
        raise backup.BackupError("R2 usage is not safe.")

    monkeypatch.setattr(backup, "remove_capture_directory", failed_remove)
    monkeypatch.setattr(backup, "run_r2_guard", reject)
    run.args.capture_only = False
    with pytest.raises(backup.BackupError, match="local retention could not complete"):
        backup.run(run.args)
    assert run.sequence[0] == 3
    for _attempt in range(3):
        with pytest.raises(backup.BackupError) as failure:
            backup.run(run.args)
        assert "synthetic-sensitive" not in str(failure.value)
        assert run.sequence[0] == 3
        assert len(list(run.root.rglob("backup.dump"))) == 3


def test_capture_timeout_is_sanitized_and_other_environment_still_captures(
    local_backup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = local_backup_run
    run.args.capture_only = True

    def capture(target, logical_dir, max_bytes):
        if target.environment == "staging":
            raise subprocess.TimeoutExpired(
                ["synthetic-sensitive-command"], 1, output="synthetic-sensitive-output"
            )
        return run.capture(target, logical_dir, max_bytes)

    monkeypatch.setattr(backup, "capture_dump", capture)
    with pytest.raises(backup.BackupError, match="failed for staging") as failure:
        backup.run(run.args)
    assert "synthetic-sensitive" not in str(failure.value)
    assert "local pair was retained" not in str(failure.value)
    assert "capture:production" in run.events
    assert len(list(run.root.rglob("backup.dump"))) == 1


def test_retry_preserves_fresh_pair_after_clock_rollback_and_retention_failure(
    local_backup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = local_backup_run
    run.targets.pop()
    run.policy["R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"] = 1
    run.args.capture_only = True
    backup.run(run.args)
    old_pair = next(run.root.rglob("backup.dump")).parent
    fresh_pair = old_pair.parent / "20260910T000000.000000Z-102-staging"
    dump, metadata = fresh_pair / "backup.dump", fresh_pair / "metadata.json"

    def backward_clock_capture(*_args):
        fresh_pair.mkdir()
        dump.write_bytes(b"fresh verified capture with earlier wall-clock timestamp")
        metadata.write_text("{}", encoding="utf-8")
        return dump, metadata, {}

    monkeypatch.setattr(backup, "capture_dump", backward_clock_capture)
    original_rename = Path.rename

    def fail_before_prune_rename(path, target):
        if path == old_pair:
            raise OSError("synthetic-sensitive-retention-failure")
        return original_rename(path, target)

    def reject(*_args):
        raise backup.BackupError("R2 usage is not safe.")

    monkeypatch.setattr(backup, "run_r2_guard", reject)
    run.args.capture_only = False
    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_before_prune_rename)
        with pytest.raises(backup.BackupError, match="local retention could not complete"):
            backup.run(run.args)

    # Retention can now run again, but timestamp sorting would delete the fresh
    # pair before a replacement exists. Refuse that guess even if capture fails.
    def failed_capture(*_args):
        pytest.fail("No new capture is allowed while the previous ring is over its bound.")

    monkeypatch.setattr(backup, "capture_dump", failed_capture)
    with pytest.raises(backup.BackupError, match="existing pairs were preserved"):
        backup.run(run.args)
    assert old_pair.exists() and dump.exists() and metadata.exists()


@pytest.mark.parametrize("capture_only", [False, True])
def test_current_capture_survives_retention_when_wall_clock_moves_backward(
    local_backup_run, monkeypatch: pytest.MonkeyPatch, capture_only: bool
) -> None:
    run = local_backup_run
    run.targets.pop()
    run.args.capture_only = True
    backup.run(run.args)
    backup.run(run.args)
    original = next(run.root.rglob("backup.dump")).parent
    earlier = original.parent / "20260910T000000.000000Z-102-staging"
    earlier.mkdir()
    dump, metadata = earlier / "backup.dump", earlier / "metadata.json"
    dump.write_bytes(b"verified newest pair after clock rollback")
    metadata.write_text("{}", encoding="utf-8")

    def reject(*_args):
        raise backup.BackupError("R2 usage is not safe.")

    def publish():
        backup.publish_snapshot(
            dump, metadata, "staging", 1, capture_only=capture_only, uploader=reject, keep_points=1
        )

    if capture_only:
        publish()
    else:
        with pytest.raises(backup.BackupError, match="local pair was retained"):
            publish()
    assert dump.exists() and metadata.exists()
    assert list(earlier.parent.iterdir()) == [earlier]


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
        "User=root",
        "Group=acops",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "RestrictAddressFamilies=AF_INET AF_UNIX",
        "CapabilityBoundingSet=",
        "ReadWritePaths=/srv/authority-closers/backups/application /run/lock",
        "TimeoutStartSec=60min",
        "TimeoutStopSec=30s",
        "Environment=AC_IPV4_ONLY=1",
        "Environment=DOCKER_CONFIG=/run/ac-docker-cli",
        "ExecStart=/usr/local/sbin/ac-postgres-backup",
        "Nice=10",
        "IOSchedulingPriority=7",
    ):
        assert marker in service

    assert "Group=root" not in service
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
        + backup.RESTIC_REPOSITORY_LOCK_WAIT_SECONDS
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
        migration_head="20260904_0018",
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


def test_repository_lock_wait_retries_only_contention_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    attempts = []

    def lock(_fd: int, _flags: int) -> None:
        attempts.append(clock[0])
        if len(attempts) < 3:
            raise OSError(errno.EAGAIN, "synthetic contention")

    monkeypatch.setattr(backup, "fcntl", SimpleNamespace(flock=lock, LOCK_EX=1, LOCK_NB=2))
    monkeypatch.setattr(backup.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        backup.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    backup.wait_for_repository_lock(9, timeout_seconds=1)
    assert attempts == [0, 0.25, 0.5]


def test_repository_lock_wait_has_a_monotonic_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]

    def lock(_fd: int, _flags: int) -> None:
        raise OSError(errno.EACCES, "synthetic contention")

    monkeypatch.setattr(backup, "fcntl", SimpleNamespace(flock=lock, LOCK_EX=1, LOCK_NB=2))
    monkeypatch.setattr(backup.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        backup.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    with pytest.raises(backup.BackupError, match="lock wait timed out"):
        backup.wait_for_repository_lock(9, timeout_seconds=0.3)
    assert clock[0] == 0.3


@pytest.mark.parametrize("error_number", [errno.EBADF, errno.EIO, errno.EPERM])
def test_repository_lock_does_not_retry_permanent_errors(
    monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    def lock(_fd: int, _flags: int) -> None:
        raise OSError(error_number, "synthetic invalid descriptor or permission")

    monkeypatch.setattr(backup, "fcntl", SimpleNamespace(flock=lock, LOCK_EX=1, LOCK_NB=2))
    monkeypatch.setattr(backup.time, "sleep", lambda _seconds: pytest.fail("must not retry"))
    with pytest.raises(backup.BackupError, match="could not be acquired safely"):
        backup.wait_for_repository_lock(9)


@pytest.mark.parametrize("wait", [0, -1, 61, float("inf"), float("nan")])
def test_repository_lock_rejects_unbounded_wait(wait: float) -> None:
    with pytest.raises(backup.BackupError, match="wait bound is invalid"):
        backup.wait_for_repository_lock(9, timeout_seconds=wait)


@pytest.mark.parametrize(
    ("diagnostic", "reason"),
    [
        (
            b"AC_BACKUP_FAILURE=repository_lock_descriptor_invalid",
            "repository_lock_descriptor_invalid",
        ),
        (b"AC_BACKUP_FAILURE=repository_lock_timeout", "repository_lock_timeout"),
        (b"AC_BACKUP_FAILURE=r2_usage_guard", "r2_usage_guard_failed"),
        (b"unable to create lock in backend", "remote_repository_lock_contention"),
        (b"AccessDenied", "remote_authorization_failed"),
        (b"no such host", "remote_name_resolution_failed"),
        (b"unrecognized synthetic provider details", "command_failed"),
    ],
)
def test_upload_failure_diagnostics_are_fixed_labels(diagnostic: bytes, reason: str) -> None:
    assert backup.upload_failure_reason(diagnostic + b" token=synthetic-private-value") == reason


def test_upload_failure_drains_bounded_stderr_without_emitting_child_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('synthetic-private-value' * 10000); "
        "sys.stderr.write('\\nAC_BACKUP_FAILURE=repository_lock_descriptor_invalid\\n'); "
        "sys.exit(17)",
    ]
    monkeypatch.setattr(backup, "upload_command", lambda *_args: command)
    observed_sizes = []
    classifier = backup.upload_failure_reason

    def classify(diagnostic: bytes) -> str:
        observed_sizes.append(len(diagnostic))
        return classifier(diagnostic)

    monkeypatch.setattr(backup, "upload_failure_reason", classify)
    with pytest.raises(backup.BackupError) as failure:
        backup.upload_dump(tmp_path / "backup.dump", tmp_path / "metadata.json", "staging", 1)
    assert "reason=repository_lock_descriptor_invalid, exit_status=17" in str(failure.value)
    assert "synthetic-private-value" not in str(failure.value)
    assert observed_sizes == [backup.UPLOAD_DIAGNOSTIC_MAX_BYTES]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(("exit_status", "reason"), [(124, "timeout"), (137, "terminated")])
def test_upload_timeout_and_termination_are_distinct_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_status: int, reason: str
) -> None:
    command_calls = []

    def command(*_args: object) -> list[str]:
        command_calls.append(True)
        return [sys.executable, "-c", f"import sys; sys.exit({exit_status})"]

    monkeypatch.setattr(backup, "upload_command", command)
    with pytest.raises(backup.BackupError, match=f"reason={reason}, exit_status={exit_status}"):
        backup.upload_dump(tmp_path / "backup.dump", tmp_path / "metadata.json", "staging", 1)
    assert command_calls == [True]

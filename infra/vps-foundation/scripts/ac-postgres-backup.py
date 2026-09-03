#!/usr/bin/env python3
"""Bounded logical PostgreSQL backup pipeline for the live application releases."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import queue
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    import grp
except ModuleNotFoundError:  # pragma: no cover - only used on the Windows dev host
    grp = None  # type: ignore[assignment]

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - only used on the Windows dev host
    fcntl = None  # type: ignore[assignment]


APPLICATION_ROOT = Path("/srv/authority-closers/application")
FOUNDATION_CURRENT = Path("/srv/authority-closers/current")
BACKUP_ROOT = Path("/srv/authority-closers/backups/application")
LOCK_ROOT = Path("/run/lock")
PRIVATE_LOCK_ROOT = LOCK_ROOT / "authority-closers"
INFISICAL_RUN = "/usr/local/sbin/ac-infisical-run"
R2_USAGE_GUARD = "/usr/local/sbin/ac-r2-usage-guard"
RESTIC_LOGICAL_BACKUP = "/usr/local/sbin/ac-infisical-run-backup"
RESTIC_LOGICAL_INNER = "/usr/local/libexec/authority-closers/ac-restic-postgres-backup-inner"
PG_DUMP_TIMEOUT_SECONDS = 4 * 60
PG_DUMP_KILL_AFTER_SECONDS = 30
PG_RESTORE_LIST_TIMEOUT_SECONDS = 60
SNAPSHOT_HOLDER_START_TIMEOUT_SECONDS = 30
SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS = 10 * 60
SNAPSHOT_HOLDER_ROLLBACK_TIMEOUT_SECONDS = 30
R2_GUARD_HTTP_RETRY_MAX_SECONDS = 75
R2_GUARD_HTTP_CALLS = 2
R2_GUARD_UNIT_TIMEOUT_SECONDS = R2_GUARD_HTTP_RETRY_MAX_SECONDS * R2_GUARD_HTTP_CALLS + 30
R2_GUARD_STOP_TIMEOUT_SECONDS = 30
R2_GUARD_CLIENT_GRACE_SECONDS = 30
R2_GUARD_CLIENT_TIMEOUT_SECONDS = (
    R2_GUARD_UNIT_TIMEOUT_SECONDS + R2_GUARD_STOP_TIMEOUT_SECONDS + R2_GUARD_CLIENT_GRACE_SECONDS
)
RESTIC_UPLOAD_TIMEOUT_SECONDS = 4 * 60
OPERATION_KILL_AFTER_SECONDS = 30
RESTIC_TAG = "authority-closers-postgres-logical"
ENVIRONMENTS = ("staging", "production")
PROFILE_KEYS = (
    "AC_COMPOSE_PROJECT",
    "AC_ENVIRONMENT",
    "AC_STATE_ROOT",
    "AC_PUBLIC_APP_URL",
    "AC_ADMIN_APP_URL",
    "AC_API_URL",
    "AC_API_HOST",
    "AC_TRUSTED_PROXY_ADDRESSES",
    "AC_EDGE_API_ALIAS",
    "AC_EDGE_LEARNER_ALIAS",
    "AC_EDGE_ADMIN_ALIAS",
    "AC_EXTERNAL_SIDE_EFFECTS_HOLD",
    "AC_EMAIL_PROVIDER",
    "AC_RELEASE_ID",
    "AC_API_IMAGE",
    "AC_LEARNER_IMAGE",
    "AC_ADMIN_IMAGE",
)
SECRET_KEYS = (
    "AC_DATABASE_URL",
    "AC_DATABASE_MIGRATOR_URL",
    "AC_POSTGRES_OWNER_PASSWORD",
    "AC_DB_MIGRATOR_PASSWORD",
    "AC_DB_RUNTIME_PASSWORD",
    "AC_DB_BACKUP_PASSWORD",
)
EXPECTED_PROFILE_VALUES = {
    "staging": {
        "AC_COMPOSE_PROJECT": "ac-application-staging",
        "AC_ENVIRONMENT": "staging",
        "AC_STATE_ROOT": "/srv/authority-closers/state/application/staging",
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "false",
        "AC_EMAIL_PROVIDER": "resend",
    },
    "production": {
        "AC_COMPOSE_PROJECT": "ac-application-production",
        "AC_ENVIRONMENT": "production",
        "AC_STATE_ROOT": "/srv/authority-closers/state/application/production",
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "true",
        "AC_EMAIL_PROVIDER": "fake",
    },
}
POLICY_KEYS = {
    "R2_MAX_STANDARD_BYTES",
    "R2_MAX_CLASS_A_MONTH",
    "R2_MAX_CLASS_B_MONTH",
    "R2_FORBID_INFREQUENT_ACCESS",
    "R2_BACKUP_BUCKET",
    "R2_OBJECT_BUCKET",
    "R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES",
    "R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT",
    "R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS",
}
ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@+%=-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAPTURE_DIR_RE = re.compile(r"^[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9]+-(staging|production)$")
EXPORTED_SNAPSHOT_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[0-9]+$")
SNAPSHOT_HOLDER_START_SQL = (
    b"BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;\nSELECT pg_export_snapshot();\n"
)
PARITY_TABLES = (
    "alembic_version",
    "persons",
    "tenants",
    "memberships",
    "programs",
    "program_versions",
    "modules",
    "module_prerequisites",
    "activities",
    "learner_version_pins",
    "enrollments",
    "enrollment_eligibility_facts",
    "enrollment_provenance",
    "entitlements",
    "activity_progress",
    "activity_drafts",
    "playback_sessions",
    "video_watch_intervals",
    "learning_evidence",
    "evidence_submissions",
    "evidence_corrections",
    "learning_progress_projections",
    "course_completion_certificates",
    "completion_snapshots",
    "certificate_events",
    "certificate_command_idempotency",
    "command_idempotency",
    "learning_command_idempotency",
    "provider_identities",
    "sessions",
    "deletion_requests",
    "authentication_replays",
    "provider_authorization_transactions",
    "outbox_events",
    "jobs",
    "operations_recovery_state",
    "provider_inbox",
    "audit_events",
    "audit_chain_heads",
)
HEALTH_CHECK_COMMAND_TIMEOUT_SECONDS = 30
HEALTH_CHECKS_PER_ENVIRONMENT = 2
BACKUP_SAFETY_MARGIN_SECONDS = 5 * 60
BACKUP_SERVICE_TIMEOUT_SECONDS = 60 * 60


def worst_case_two_environment_backup_seconds() -> int:
    """Return the conservative bound used by the backup systemd unit."""

    per_environment = (
        HEALTH_CHECK_COMMAND_TIMEOUT_SECONDS * HEALTH_CHECKS_PER_ENVIRONMENT
        + SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS
        + PG_RESTORE_LIST_TIMEOUT_SECONDS
        + PG_RESTORE_LIST_TIMEOUT_SECONDS
        + RESTIC_UPLOAD_TIMEOUT_SECONDS
        + OPERATION_KILL_AFTER_SECONDS
        + 30
        + R2_GUARD_CLIENT_TIMEOUT_SECONDS
    )
    return (
        len(ENVIRONMENTS) * per_environment
        + R2_GUARD_CLIENT_TIMEOUT_SECONDS
        + BACKUP_SAFETY_MARGIN_SECONDS
    )


class BackupError(RuntimeError):
    """A safe, operator-facing failure without command or secret output."""


@dataclass(frozen=True)
class ApplicationTarget:
    environment: str
    current_link: Path
    release_dir: Path
    profile_file: Path
    images_file: Path
    state_root: Path
    compose_project: str
    secret_environment: str


@dataclass
class ExportedSnapshotHolder:
    """A bounded read-only PostgreSQL transaction exporting one snapshot."""

    process: subprocess.Popen[bytes]
    snapshot_id: str
    started_at: float
    closed: bool = False

    def assert_alive(self) -> None:
        if self.closed or self.process.poll() is not None:
            raise BackupError("The PostgreSQL exported-snapshot holder exited early.")
        if time.monotonic() - self.started_at > SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS:
            self.close()
            raise BackupError("The PostgreSQL exported-snapshot holder exceeded its lifetime.")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        rollback_error: OSError | None = None
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.write(b"ROLLBACK;\n\\q\n")
                self.process.stdin.flush()
                self.process.stdin.close()
            except OSError as error:
                rollback_error = error
            if rollback_error is None:
                try:
                    self.process.wait(timeout=SNAPSHOT_HOLDER_ROLLBACK_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as error:
                    terminate_process(self.process)
                    raise BackupError(
                        "The PostgreSQL exported-snapshot holder rollback timed out."
                    ) from error
            else:
                terminate_process(self.process)
                raise BackupError(
                    "The PostgreSQL exported-snapshot holder rollback failed."
                ) from rollback_error
        if self.process.returncode not in (0, None):
            raise BackupError("The PostgreSQL exported-snapshot holder failed during cleanup.")


def validate_exported_snapshot_id(value: str) -> str:
    if not isinstance(value, str) or EXPORTED_SNAPSHOT_RE.fullmatch(value) is None:
        raise BackupError("The PostgreSQL exported snapshot identity is invalid.")
    return value


def snapshot_holder_command(target: ApplicationTarget) -> list[str]:
    return [
        "timeout",
        "--foreground",
        f"--kill-after={PG_DUMP_KILL_AFTER_SECONDS}s",
        f"{SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS}s",
        *compose_command(
            target,
            "exec",
            "-T",
            "postgres",
            "sh",
            "-euc",
            'export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
            "exec psql --no-password -h 127.0.0.1 -U ac_backup "
            '-d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1',
        ),
    ]


def start_exported_snapshot_holder(target: ApplicationTarget) -> ExportedSnapshotHolder:
    try:
        process = subprocess.Popen(  # noqa: S603 - command uses fixed release paths
            snapshot_holder_command(target),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=compose_environment(target),
            start_new_session=(os.name == "posix"),
        )
    except OSError as error:
        raise BackupError("The PostgreSQL exported-snapshot holder could not start.") from error
    try:
        assert process.stdin is not None
        process.stdin.write(SNAPSHOT_HOLDER_START_SQL)
        process.stdin.flush()
    except OSError as error:
        try:
            terminate_process(process)
        except OSError as cleanup_error:
            raise BackupError(
                "The PostgreSQL exported-snapshot holder startup cleanup failed."
            ) from cleanup_error
        raise BackupError("The PostgreSQL exported-snapshot holder protocol failed.") from error
    assert process.stdout is not None
    output_queue: queue.Queue[object] = queue.Queue(maxsize=1)

    def read_snapshot_line() -> None:
        try:
            output_queue.put(process.stdout.readline())
        except OSError as error:
            output_queue.put(error)

    reader = threading.Thread(target=read_snapshot_line, daemon=True)
    reader.start()
    try:
        line = output_queue.get(timeout=SNAPSHOT_HOLDER_START_TIMEOUT_SECONDS)
    except queue.Empty as error:
        try:
            terminate_process(process)
        except OSError as cleanup_error:
            raise BackupError(
                "The PostgreSQL exported-snapshot holder startup cleanup failed."
            ) from cleanup_error
        raise BackupError("The PostgreSQL exported-snapshot holder startup timed out.") from error
    if isinstance(line, OSError):
        terminate_process(process)
        raise BackupError(
            "The PostgreSQL exported-snapshot holder output was unreadable."
        ) from line
    if not isinstance(line, bytes) or len(line) > 128 or not line.endswith(b"\n"):
        terminate_process(process)
        raise BackupError("The PostgreSQL exported-snapshot holder returned an invalid identity.")
    try:
        snapshot_id = validate_exported_snapshot_id(line.decode("ascii").strip())
    except (UnicodeDecodeError, BackupError) as error:
        terminate_process(process)
        if isinstance(error, BackupError):
            raise
        raise BackupError(
            "The PostgreSQL exported-snapshot holder returned an invalid identity."
        ) from error
    if process.poll() is not None:
        raise BackupError("The PostgreSQL exported-snapshot holder exited before the dump.")
    return ExportedSnapshotHolder(process, snapshot_id, time.monotonic())


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def timestamp(value: dt.datetime | None = None) -> str:
    value = value or utc_now()
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def host_path(host_root: Path, absolute_path: str | Path) -> Path:
    path = PurePosixPath(str(absolute_path).replace("\\", "/"))
    if not path.is_absolute():
        raise BackupError("An operational path must be absolute.")
    relative = Path(*path.parts[1:])
    return host_root / relative if host_root != Path("/") else Path("/", relative)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BackupError("Application release profile is not readable.") from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise BackupError("Application release profile is malformed.")
        if not ENV_VALUE_RE.fullmatch(value):
            raise BackupError("Application release profile contains unsafe syntax.")
        values[key] = value
    return values


def verify_release_files(release_dir: Path) -> None:
    manifest = release_dir / "RELEASE-FILES.sha256"
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BackupError("Current application release lacks checksum evidence.") from exc
    for line in lines:
        digest, separator, relative = line.partition("  ")
        relative = relative.removeprefix("./")
        candidate = (release_dir / relative).resolve()
        if (
            not separator
            or not SHA256_RE.fullmatch(digest)
            or not relative
            or Path(relative).is_absolute()
            or release_dir not in candidate.parents
            or not candidate.is_file()
        ):
            raise BackupError("Current application release checksum evidence is malformed.")
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != digest:
            raise BackupError("Current application release checksum verification failed.")


def resolve_application_release(
    environment: str,
    *,
    host_root: Path = Path("/"),
    allow_missing: bool = False,
) -> ApplicationTarget | None:
    if environment not in ENVIRONMENTS:
        raise BackupError("Unsupported application environment.")
    application_root = host_path(host_root, APPLICATION_ROOT)
    current_link = application_root / f"current-{environment}"
    if not current_link.exists() and not current_link.is_symlink():
        if allow_missing:
            return None
        raise BackupError(f"The current {environment} application release is absent.")
    if not current_link.is_symlink():
        raise BackupError(f"The current {environment} application path is not a symlink.")
    try:
        release_dir = current_link.resolve(strict=True)
    except OSError as exc:
        raise BackupError(f"The current {environment} application release is broken.") from exc
    releases_root = application_root / "releases"
    if release_dir.parent != releases_root or not re.fullmatch(r"[0-9a-f]{40}", release_dir.name):
        raise BackupError(
            f"The current {environment} application release is outside its immutable root."
        )
    verify_release_files(release_dir)
    profile_file = release_dir / "environments" / f"{environment}.env"
    images_file = release_dir / "release-images.env"
    profile = parse_env_file(profile_file)
    for key, expected in EXPECTED_PROFILE_VALUES[environment].items():
        if profile.get(key) != expected:
            raise BackupError(f"The current {environment} application profile is not exact.")
    state_root = host_path(host_root, profile["AC_STATE_ROOT"])
    if not state_root.is_dir() or state_root.is_symlink():
        raise BackupError(f"The current {environment} application state root is absent or unsafe.")
    if not images_file.is_file() or not (release_dir / "compose.yaml").is_file():
        raise BackupError(f"The current {environment} application compose release is incomplete.")
    return ApplicationTarget(
        environment=environment,
        current_link=current_link,
        release_dir=release_dir,
        profile_file=profile_file,
        images_file=images_file,
        state_root=state_root,
        compose_project=profile["AC_COMPOSE_PROJECT"],
        secret_environment="prod" if environment == "production" else environment,
    )


def resolve_targets(
    *, host_root: Path = Path("/"), requested_environment: str | None = None
) -> list[ApplicationTarget]:
    if requested_environment:
        target = resolve_application_release(
            requested_environment, host_root=host_root, allow_missing=False
        )
        return [target] if target else []
    staging = resolve_application_release("staging", host_root=host_root, allow_missing=False)
    production = resolve_application_release("production", host_root=host_root, allow_missing=True)
    return [target for target in (staging, production) if target is not None]


def compose_command(target: ApplicationTarget, *arguments: str) -> list[str]:
    command = [
        INFISICAL_RUN,
        "--",
        "env",
    ]
    for key in PROFILE_KEYS:
        command.extend(("-u", key))
    command.extend(
        (
            "docker",
            "compose",
            "--project-directory",
            str(target.release_dir),
            "--project-name",
            target.compose_project,
            "--env-file",
            str(target.profile_file),
            "--env-file",
            str(target.images_file),
            "--file",
            str(target.release_dir / "compose.yaml"),
            *arguments,
        )
    )
    return command


def compose_environment(target: ApplicationTarget) -> dict[str, str]:
    environment = os.environ.copy()
    environment["AC_INFISICAL_ENVIRONMENT"] = target.secret_environment
    environment["AC_INFISICAL_PATH"] = "/application"
    for key in (*PROFILE_KEYS, *SECRET_KEYS):
        environment.pop(key, None)
    return environment


def run_checked(
    command: list[str],
    *,
    target: ApplicationTarget | None = None,
    timeout_seconds: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - command is assembled from fixed release paths and allow-listed values
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=compose_environment(target) if target else None,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError("The bounded backup command failed.") from exc


def assert_healthy(target: ApplicationTarget) -> None:
    result = run_checked(compose_command(target, "ps", "-q", "postgres"), target=target)
    container_id = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise BackupError(f"The {target.environment} postgres container is not present.")
    try:
        health = subprocess.run(  # noqa: S603 - container ID is validated before use
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],  # noqa: S607
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f"The {target.environment} postgres health check failed.") from exc
    if health != "healthy":
        raise BackupError(f"The {target.environment} postgres container is not healthy.")


def read_policy(path: Path) -> dict[str, int | str]:
    values: dict[str, int | str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BackupError("R2 policy is not readable.") from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in POLICY_KEYS or key in values:
            raise BackupError("R2 policy contains an unknown or duplicate assignment.")
        if key.endswith("BUCKET"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", value):
                raise BackupError("R2 policy contains an unsafe bucket name.")
            values[key] = value
        else:
            if not value.isdigit():
                raise BackupError("R2 policy numeric values must be non-negative integers.")
            values[key] = int(value)
    required = {
        "R2_MAX_STANDARD_BYTES",
        "R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES",
        "R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT",
        "R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS",
    }
    if not required.issubset(values):
        raise BackupError("R2 policy lacks the logical PostgreSQL storage model.")
    return values


def projected_logical_bytes(policy: dict[str, int | str]) -> int:
    result = (
        int(policy["R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES"])
        * int(policy["R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"])
        * int(policy["R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS"])
    )
    if result <= 0 or result > int(policy["R2_MAX_STANDARD_BYTES"]):
        raise BackupError("The logical PostgreSQL storage projection is outside the R2 envelope.")
    return result


def run_r2_guard(projected_bytes: int) -> None:
    environment = os.environ.copy()
    environment["R2_PROJECTED_ADDITIONAL_BYTES"] = str(projected_bytes)
    try:
        subprocess.run(  # noqa: S603 - fixed installed usage-guard path
            [R2_USAGE_GUARD],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=R2_GUARD_CLIENT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError("R2 usage or projected logical-dump storage is not safe.") from exc


def dump_command(target: ApplicationTarget, snapshot_id: str) -> list[str]:
    snapshot_id = validate_exported_snapshot_id(snapshot_id)
    return [
        "timeout",
        "--foreground",
        f"--kill-after={PG_DUMP_KILL_AFTER_SECONDS}s",
        f"{PG_DUMP_TIMEOUT_SECONDS}s",
        *compose_command(
            target,
            "exec",
            "-T",
            "postgres",
            "sh",
            "-euc",
            'umask 077; export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
            "exec pg_dump --no-password -h 127.0.0.1 "
            f'-U ac_backup -d "$POSTGRES_DB" --format=custom --create --snapshot={snapshot_id}',
        ),
    ]


def parity_command(target: ApplicationTarget, snapshot_id: str) -> list[str]:
    snapshot_id = validate_exported_snapshot_id(snapshot_id)
    query = " UNION ALL ".join(
        f"SELECT '{table}', count(*)::bigint FROM \"{table}\""  # noqa: S608 - table names are fixed above
        for table in PARITY_TABLES
    )
    snapshot_query = (
        "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY; "
        f"SET TRANSACTION SNAPSHOT '{snapshot_id}'; "
        f"{query}; COMMIT;"
    )
    return compose_command(
        target,
        "exec",
        "-T",
        "postgres",
        "sh",
        "-euc",
        'export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
        "exec psql --no-password --no-psqlrc --set=ON_ERROR_STOP=1 "
        '-h 127.0.0.1 -U ac_backup -d "$POSTGRES_DB" -qAt '
        '-c "$1"',
        "--",
        snapshot_query,
    )


def source_row_counts(target: ApplicationTarget, snapshot_id: str) -> dict[str, int]:
    result = run_checked(
        parity_command(target, snapshot_id),
        target=target,
        timeout_seconds=PG_RESTORE_LIST_TIMEOUT_SECONDS,
    ).stdout.splitlines()
    counts: dict[str, int] = {}
    for line in result:
        table, separator, count = line.partition("|")
        if not separator or table not in PARITY_TABLES or table in counts or not count.isdigit():
            raise BackupError("The source PostgreSQL parity query returned an unsafe result.")
        counts[table] = int(count)
    if set(counts) != set(PARITY_TABLES):
        raise BackupError("The source PostgreSQL parity query was incomplete.")
    return counts


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=PG_DUMP_KILL_AFTER_SECONDS)
            return
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.wait()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_directory(path: Path) -> None:
    if path.is_symlink():
        raise BackupError("The logical backup directory must not be a symlink.")
    path.mkdir(mode=0o750, parents=True, exist_ok=True)
    path.chmod(0o750)
    if grp is None:
        raise BackupError("The Linux ownership implementation is unavailable.")
    try:
        os.chown(path, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
    except (KeyError, OSError) as exc:
        raise BackupError(
            "The logical backup directory must be root-owned and acops-readable."
        ) from exc


def is_root_owned(path: Path) -> bool:
    """Return whether *path* is owned by root without following symlinks."""
    return getattr(path.lstat(), "st_uid", None) == 0


def remove_capture_directory(path: Path, *, temporary: bool) -> None:
    if path.is_symlink() or not path.is_dir() or not is_root_owned(path):
        raise BackupError("A logical-backup capture directory is unsafe.")
    allowed_names = {"backup.dump", "metadata.json"}
    for candidate in path.iterdir():
        if (
            candidate.name not in allowed_names
            or candidate.is_symlink()
            or not candidate.is_file()
            or not is_root_owned(candidate)
        ):
            raise BackupError("A logical-backup capture directory contains an unsafe entry.")
        candidate.unlink()
    if not temporary and any(path.iterdir()):
        raise BackupError("A logical-backup capture directory could not be emptied safely.")
    path.rmdir()


def remove_stale_temporaries(path: Path, environment: str) -> None:
    for candidate in path.iterdir():
        if candidate.name.startswith(f".{environment}-") and candidate.name.endswith(
            ".capture.tmp"
        ):
            remove_capture_directory(candidate, temporary=True)
        elif candidate.name.startswith(".prune-"):
            capture_name = candidate.name.removeprefix(".prune-")
            match = CAPTURE_DIR_RE.fullmatch(capture_name)
            if match is None or match.group(1) != environment:
                raise BackupError("A stale logical-backup prune path is unsafe.")
            remove_capture_directory(candidate, temporary=True)


def fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def capture_dump(
    target: ApplicationTarget, logical_dir: Path, max_bytes: int
) -> tuple[Path, Path, dict[str, object]]:
    prepare_directory(logical_dir)
    remove_stale_temporaries(logical_dir, target.environment)
    started_at = timestamp()
    temporary_name = tempfile.mkdtemp(
        prefix=f".{target.environment}-", suffix=".capture.tmp", dir=logical_dir
    )
    temporary_dir = Path(temporary_name)
    temporary_dir.chmod(0o750)
    if grp is None:
        temporary_dir.rmdir()
        raise BackupError("The Linux ownership implementation is unavailable.")
    try:
        os.chown(temporary_dir, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
    except (KeyError, OSError) as exc:
        temporary_dir.rmdir()
        raise BackupError("The logical capture must be root-owned and acops-readable.") from exc
    temporary_path = temporary_dir / "backup.dump"
    metadata_path_tmp = temporary_dir / "metadata.json"
    snapshot_holder: ExportedSnapshotHolder | None = None
    process: subprocess.Popen[bytes] | None = None
    bytes_written = 0
    try:
        snapshot_holder = start_exported_snapshot_holder(target)
        snapshot_holder.assert_alive()
        process = subprocess.Popen(  # noqa: S603 - command is fixed to the exact compose release and timeout
            dump_command(target, snapshot_holder.snapshot_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=compose_environment(target),
            start_new_session=(os.name == "posix"),
        )
        assert process.stdout is not None
        with temporary_path.open("wb") as destination:
            while True:
                chunk = process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    terminate_process(process)
                    raise BackupError(
                        f"The {target.environment} logical dump exceeded its fixed size bound."
                    )
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if process.wait() != 0:
            raise BackupError(f"The {target.environment} logical dump command failed.")
        if bytes_written == 0:
            raise BackupError(f"The {target.environment} logical dump was empty.")
        with temporary_path.open("rb") as verified_dump:
            restore_result = subprocess.run(  # noqa: S603 - command is fixed to the exact compose release
                compose_command(target, "exec", "-T", "postgres", "pg_restore", "--list"),
                stdin=verified_dump,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=compose_environment(target),
                timeout=PG_RESTORE_LIST_TIMEOUT_SECONDS,
            )
        if restore_result.returncode != 0:
            raise BackupError(
                f"The {target.environment} logical dump failed pg_restore --list verification."
            )
        snapshot_holder.assert_alive()
        row_counts = source_row_counts(target, snapshot_holder.snapshot_id)
        snapshot_holder.close()
        snapshot_holder = None
        completed_time = utc_now()
        completed_at = timestamp(completed_time)
        captured_at_epoch_ns = time.time_ns()
        capture_id = f"{completed_time.strftime('%Y%m%dT%H%M%S.%fZ')}-{os.getpid()}"
        digest = sha256_file(temporary_path)
        metadata: dict[str, object] = {
            "artifact_type": "authority-closers-postgresql-logical",
            "restic_tag": RESTIC_TAG,
            "environment": target.environment,
            "release_id": target.release_dir.name,
            "compose_project": target.compose_project,
            "database_role": "ac_backup",
            "format": "custom",
            "verification": "pg_restore --list",
            "capture_started_at": started_at,
            "capture_completed_at": completed_at,
            "captured_at": completed_at,
            "captured_at_epoch_ns": captured_at_epoch_ns,
            "capture_clock": "CLOCK_REALTIME",
            "dump_bytes": bytes_written,
            "dump_sha256": digest,
            "row_counts": row_counts,
        }
        metadata_fd = os.open(
            metadata_path_tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o640,
        )
        with os.fdopen(metadata_fd, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, sort_keys=True, separators=(",", ":"))
            metadata_file.write("\n")
            metadata_file.flush()
            os.fsync(metadata_file.fileno())
        metadata_path_tmp.chmod(0o640)
        if grp is None:
            raise BackupError("The Linux ownership implementation is unavailable.")
        try:
            os.chown(metadata_path_tmp, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
            temporary_path.chmod(0o640)
            os.chown(temporary_path, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
        except (KeyError, OSError) as exc:
            raise BackupError(
                "Logical capture files must be root-owned and acops-readable."
            ) from exc
        capture_dir = logical_dir / f"{capture_id}-{target.environment}"
        dump_path = capture_dir / "backup.dump"
        metadata_path = capture_dir / "metadata.json"
        if capture_dir.exists() or capture_dir.is_symlink():
            raise BackupError("The logical capture identity already exists.")
        fsync_directory(temporary_dir)
        temporary_dir.rename(capture_dir)
        fsync_directory(logical_dir)
        return dump_path, metadata_path, metadata
    except Exception:
        cleanup_error: Exception | None = None
        if process is not None and process.poll() is None:
            try:
                terminate_process(process)
            except Exception as error:
                cleanup_error = error
        if snapshot_holder is not None:
            try:
                snapshot_holder.close()
            except Exception as error:
                cleanup_error = error
        if temporary_dir.exists() and not temporary_dir.is_symlink():
            try:
                remove_capture_directory(temporary_dir, temporary=True)
            except Exception as error:
                cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise BackupError(
                "Logical backup snapshot or temporary cleanup failed."
            ) from cleanup_error
        raise


def prune_local_ring(logical_dir: Path, keep_points: int) -> None:
    environment = logical_dir.parent.name
    if environment not in ENVIRONMENTS or keep_points <= 0:
        raise BackupError("The local logical-backup ring identity is invalid.")
    remove_stale_temporaries(logical_dir, environment)
    captures: list[Path] = []
    for candidate in sorted(logical_dir.iterdir()):
        match = CAPTURE_DIR_RE.fullmatch(candidate.name)
        if match is None or match.group(1) != environment:
            raise BackupError("The local logical-backup ring contains an unknown entry.")
        if candidate.is_symlink() or not candidate.is_dir() or not is_root_owned(candidate):
            raise BackupError("The local logical-backup ring contains an incomplete pair.")
        entries = {entry.name: entry for entry in candidate.iterdir()}
        if set(entries) != {"backup.dump", "metadata.json"} or any(
            entry.is_symlink() or not entry.is_file() or not is_root_owned(entry)
            for entry in entries.values()
        ):
            raise BackupError("The local logical-backup ring contains an incomplete pair.")
        captures.append(candidate)
    recent_captures = set(captures[-keep_points:])
    for capture_dir in captures:
        if capture_dir in recent_captures:
            continue
        prune_path = logical_dir / f".prune-{capture_dir.name}"
        if prune_path.exists() or prune_path.is_symlink():
            raise BackupError("The local logical-backup prune identity already exists.")
        capture_dir.rename(prune_path)
        fsync_directory(logical_dir)
        remove_capture_directory(prune_path, temporary=False)
        fsync_directory(logical_dir)


@contextlib.contextmanager
def secure_lock_file(host_root: Path, filename: str) -> Iterator[int]:
    if fcntl is None:
        raise BackupError("The Linux file-lock implementation is unavailable.")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise BackupError("The Linux no-follow lock boundary is unavailable.")
    lock_parent = host_path(host_root, LOCK_ROOT)
    lock_parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if host_root == Path("/"):
        parent_stat = os.stat(lock_parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != 0
            or not parent_stat.st_mode & stat.S_ISVTX
        ):
            raise BackupError("The system lock parent is not a root-owned sticky directory.")
    lock_directory = host_path(host_root, PRIVATE_LOCK_ROOT)
    with contextlib.suppress(FileExistsError):
        lock_directory.mkdir(mode=0o750)
    try:
        directory_fd = os.open(
            lock_directory,
            os.O_RDONLY | os.O_CLOEXEC | directory_flag | no_follow,
        )
    except OSError as exc:
        raise BackupError("The private lock directory could not be opened safely.") from exc
    expected_uid = 0 if host_root == Path("/") else os.geteuid()
    expected_gid = os.getegid()
    if host_root == Path("/"):
        if grp is None:
            os.close(directory_fd)
            raise BackupError("The system group database is unavailable.")
        try:
            expected_gid = grp.getgrnam("acops").gr_gid
        except KeyError as exc:
            os.close(directory_fd)
            raise BackupError("The acops group is unavailable.") from exc
    lock_fd: int | None = None
    try:
        try:
            directory_stat = os.fstat(directory_fd)
            if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != expected_uid:
                raise BackupError("The private lock directory has an unsafe identity.")
            os.fchmod(directory_fd, 0o750)
            os.fchown(directory_fd, expected_uid, expected_gid)
            lock_fd = os.open(
                filename,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | no_follow,
                0o640,
                dir_fd=directory_fd,
            )
            lock_stat = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or lock_stat.st_uid != expected_uid
                or lock_stat.st_nlink != 1
            ):
                raise BackupError("The lock file has an unsafe identity.")
            os.fchmod(lock_fd, 0o640)
            os.fchown(lock_fd, expected_uid, expected_gid)
        except OSError as exc:
            raise BackupError("The private lock boundary could not be opened safely.") from exc
        yield lock_fd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)


@contextlib.contextmanager
def repository_lock(host_root: Path) -> Iterator[int]:
    with secure_lock_file(host_root, "ac-restic-repository.lock") as lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BackupError(
                "Another Restic backup, prune, or logical dump is already active."
            ) from exc
        yield lock_fd


@contextlib.contextmanager
def environment_lock(environment: str, host_root: Path) -> Iterator[None]:
    with secure_lock_file(host_root, f"ac-postgres-backup-{environment}.lock") as lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BackupError(f"Another {environment} logical backup is already active.") from exc
        yield


def upload_command(
    dump_path: Path,
    metadata_path: Path,
    environment: str,
) -> list[str]:
    return [
        "timeout",
        "--foreground",
        f"--kill-after={OPERATION_KILL_AFTER_SECONDS}s",
        f"{RESTIC_UPLOAD_TIMEOUT_SECONDS}s",
        RESTIC_LOGICAL_BACKUP,
        "--",
        RESTIC_LOGICAL_INNER,
        str(dump_path),
        str(metadata_path),
        environment,
    ]


def upload_dump(
    dump_path: Path,
    metadata_path: Path,
    environment: str,
    projected_bytes: int,
    *,
    repository_lock_fd: int | None = None,
) -> None:
    environment_vars = os.environ.copy()
    environment_vars["R2_PROJECTED_ADDITIONAL_BYTES"] = str(projected_bytes)
    command = upload_command(dump_path, metadata_path, environment)
    if repository_lock_fd is not None:
        environment_vars["AC_RESTIC_LOCK_FD"] = str(repository_lock_fd)
    try:
        run_options = {
            "check": True,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": environment_vars,
        }
        if os.name == "posix" and repository_lock_fd is not None:
            run_options["pass_fds"] = (repository_lock_fd,)
        subprocess.run(  # noqa: S603 - command is fixed to the installed Infisical/Restic wrappers
            command,
            timeout=RESTIC_UPLOAD_TIMEOUT_SECONDS + OPERATION_KILL_AFTER_SECONDS + 30,
            **run_options,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError(
            "The encrypted off-host logical snapshot failed; the local dump was retained."
        ) from exc


def publish_snapshot(
    dump_path: Path,
    metadata_path: Path,
    environment: str,
    projected_bytes: int,
    *,
    capture_only: bool,
    uploader: Callable[[Path, Path, str, int], None] = upload_dump,
    pruner: Callable[[Path, int], None] = prune_local_ring,
    keep_points: int,
) -> None:
    if (
        dump_path.name != "backup.dump"
        or metadata_path.name != "metadata.json"
        or dump_path.parent != metadata_path.parent
    ):
        raise BackupError("The logical snapshot pair does not use the atomic capture contract.")
    logical_dir = dump_path.parent.parent
    if not capture_only:
        try:
            uploader(dump_path, metadata_path, environment, projected_bytes)
        except Exception:
            # Bound repeated off-host failures while always retaining the
            # just-verified dump, which is the newest ring member.
            with contextlib.suppress(Exception):
                pruner(logical_dir, keep_points)
            raise
    # Retention is deliberately after upload. A failed off-host write leaves
    # the verified local dump and its metadata in the bounded ring.
    pruner(logical_dir, keep_points)


def run(args: argparse.Namespace) -> None:
    if os.geteuid() != 0:
        raise BackupError("The logical backup must run as root.")
    if args.environment and args.environment not in ENVIRONMENTS:
        raise BackupError("Unsupported application environment.")
    host_root = Path(os.environ.get("AC_POSTGRES_BACKUP_HOST_ROOT", "/")).resolve()
    foundation_current = host_path(host_root, FOUNDATION_CURRENT)
    policy_path = foundation_current / "config/r2/free-tier-policy.conf"
    policy = read_policy(policy_path)
    max_dump_bytes = int(policy["R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES"])
    keep_points = int(policy["R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"])
    projected_bytes = projected_logical_bytes(policy)
    targets = resolve_targets(host_root=host_root, requested_environment=args.environment)
    for target in targets:
        assert_healthy(target)
    run_r2_guard(projected_bytes)
    if args.dry_run:
        return
    for target in targets:
        logical_dir = host_path(host_root, BACKUP_ROOT) / target.environment / "logical"
        with environment_lock(target.environment, host_root):
            dump_path, metadata_path, _metadata = capture_dump(target, logical_dir, max_dump_bytes)

            def locked_upload(
                dump: Path,
                metadata: Path,
                environment: str,
                projected: int,
            ) -> None:
                with repository_lock(host_root) as repository_lock_fd:
                    run_r2_guard(projected)
                    upload_dump(
                        dump,
                        metadata,
                        environment,
                        projected,
                        repository_lock_fd=repository_lock_fd,
                    )

            publish_snapshot(
                dump_path,
                metadata_path,
                target.environment,
                projected_bytes,
                capture_only=args.capture_only,
                uploader=locked_upload,
                keep_points=keep_points,
            )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--dry-run", action="store_true", help="validate release, health, and R2 projection only"
    )
    result.add_argument(
        "--capture-only",
        action="store_true",
        help="capture and verify locally without an off-host write",
    )
    result.add_argument(
        "--environment", choices=ENVIRONMENTS, help="limit a run to one exact application release"
    )
    return result


if __name__ == "__main__":
    try:
        run(parser().parse_args())
    except BackupError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        sys.exit(1)

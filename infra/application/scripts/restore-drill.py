#!/usr/bin/env python3
"""Run an opt-in PostgreSQL restore drill in disposable Docker resources.

The host-side program is Python-stdlib-only. Application recovery code runs
inside an explicitly supplied, locally loaded application image and may connect
only to the generated PostgreSQL identity on an internal Docker network.

The default is a non-mutating plan. ``--execute`` and
``--acknowledge-isolated-target`` are both required before any directory or
Docker resource is created.
"""

# Docker arguments and SQL identifiers below are fixed or generated from
# validated tokens. Subprocesses never use a shell, and secret values are
# passed through process environments rather than command arguments.
# ruff: noqa: S603, S607, S608, S108

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any
from urllib.parse import quote
from uuid import UUID

DEFAULT_POSTGRES_IMAGE = (
    "postgres@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
)
RPO_TARGET_SECONDS = 15 * 60
RTO_TARGET_SECONDS = 60 * 60
MAX_RELEASE_SET_SIZE = 100
DOCKER_TIMEOUT_SECONDS = 30
QUERY_TIMEOUT_SECONDS = 15
DATABASE_READY_TIMEOUT_SECONDS = 180
RESTORE_LIST_TIMEOUT_SECONDS = 60
RESTORE_TIMEOUT_SECONDS = 60 * 60
HELPER_TIMEOUT_SECONDS = 180
MAX_BACKUP_BYTES = 8 * 1024 * 1024
LABEL_KEY = "authority-closers.restore-drill.run"
PROBE_ACKNOWLEDGEMENT = "isolated-disposable-restore-drill-v1"
STABLE_INPUT_ROOT = (
    Path("/var/lib/authority-closers/restore-drill-inputs")
    if os.name == "posix"
    else Path(tempfile.gettempdir()) / "authority-closers-restore-drill-inputs"
)

TOKEN_PATTERN = re.compile(r"^[0-9a-f]{12}$")
BASE_NAME_PATTERN = re.compile(r"^ac-restore-drill-[0-9a-f]{12}$")
DATABASE_NAME_PATTERN = re.compile(r"^ac_restore_drill_[0-9a-f]{12}$")
ROLE_NAME_PATTERN = re.compile(r"^ac_restore_owner_[0-9a-f]{12}$")
APPLICATION_IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
POSTGRES_IMAGE_PATTERN = re.compile(r"^postgres@sha256:[0-9a-f]{64}$")
MIGRATION_PATTERN = re.compile(r"^[0-9]{8}_[0-9]{4}$")
RELEASE_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
STABLE_INPUT_DIR_PATTERN = re.compile(r"^\.input-[0-9a-f]{24}$")

# Stable representative contract. Payloads, addresses, provider receipts, and
# other potentially sensitive values are never selected for evidence.
CANONICAL_TABLES = (
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

# Explicit compatibility catalogue, not a lexical version comparison or table
# presence heuristic. Any later migration needs a reviewed parity decision.
LEGACY_PARITY_MIGRATION_HEADS = frozenset(
    {
        "20260830_0006",
        "20260830_0007",
        "20260830_0008",
        "20260830_0009",
        "20260830_0010",
        "20260830_0011",
        "20260901_0012",
        "20260902_0013",
        "20260902_0014",
        "20260903_0015",
        "20260903_0016",
        "20260904_0017",
        "20260904_0018",
    }
)
CAPABILITY_PARITY_MIGRATION_HEAD = "20260907_0019"
CAPABILITY_PARITY_CONTRACT = "ac-postgres-parity-v2"
CAPABILITY_PARITY_TABLES = CANONICAL_TABLES + ("capability_grants", "capability_revocations")


PRACTICE_PARITY_MIGRATION_HEAD = "20260908_0020"
PRACTICE_PARITY_CONTRACT = "ac-postgres-parity-v3"
PRACTICE_PARITY_TABLES = CAPABILITY_PARITY_TABLES + (
    "practice_set_versions",
    "practice_attempts",
    "practice_profiles",
    "practice_responses",
    "practice_commands",
    "practice_feedback_acks",
    "practice_participations",
    "practice_reward_claims",
    "practice_ledger_entries",
)
FOCUS_PARITY_MIGRATION_HEAD = "20260908_0021"
FOCUS_PARITY_CONTRACT = "ac-postgres-parity-v4"
FOCUS_PARITY_TABLES = PRACTICE_PARITY_TABLES + ("practice_focus_runs", "practice_focus_events")
AUTHORING_PARITY_MIGRATION_HEAD = "20260908_0022"
AUTHORING_PARITY_CONTRACT = "ac-postgres-parity-v5"
AUTHORING_PARITY_TABLES = FOCUS_PARITY_TABLES + ("catalog_authoring_commands",)
# 20260909_0023 extends the immutable authoring-command operation catalogue
# without changing the restored table inventory or its parity contract.
REVISION_PARITY_MIGRATION_HEAD = "20260909_0023"
REVISION_PARITY_CONTRACT = AUTHORING_PARITY_CONTRACT
REVISION_PARITY_TABLES = AUTHORING_PARITY_TABLES
VERSIONED_PARITY_CONTRACTS = {
    CAPABILITY_PARITY_MIGRATION_HEAD: (CAPABILITY_PARITY_CONTRACT, CAPABILITY_PARITY_TABLES),
    PRACTICE_PARITY_MIGRATION_HEAD: (PRACTICE_PARITY_CONTRACT, PRACTICE_PARITY_TABLES),
    FOCUS_PARITY_MIGRATION_HEAD: (FOCUS_PARITY_CONTRACT, FOCUS_PARITY_TABLES),
    AUTHORING_PARITY_MIGRATION_HEAD: (AUTHORING_PARITY_CONTRACT, AUTHORING_PARITY_TABLES),
    REVISION_PARITY_MIGRATION_HEAD: (REVISION_PARITY_CONTRACT, REVISION_PARITY_TABLES),
}


def parity_tables_for_head(migration_head: str) -> tuple[str, ...]:
    if migration_head in LEGACY_PARITY_MIGRATION_HEADS:
        return CANONICAL_TABLES
    if migration_head in VERSIONED_PARITY_CONTRACTS:
        return VERSIONED_PARITY_CONTRACTS[migration_head][1]
    raise DrillError("migration head has no reviewed row-count parity contract")


def parity_contract_for_head(migration_head: str) -> str | None:
    parity_tables_for_head(migration_head)
    if migration_head in LEGACY_PARITY_MIGRATION_HEADS:
        return None
    return VERSIONED_PARITY_CONTRACTS[migration_head][0]


SIDE_EFFECT_COUNTS_QUERY = """
SELECT
  (SELECT count(*) FROM outbox_events WHERE status = 'pending') AS pending_outbox,
  (SELECT count(*) FROM jobs
   WHERE external_side_effect
     AND status NOT IN ('held', 'succeeded', 'dead_letter')) AS uncertain_external_jobs,
  (SELECT count(*) FROM outbox_events WHERE status = 'held') AS held_outbox,
  (SELECT count(*) FROM jobs WHERE external_side_effect AND status = 'held')
    AS held_external_jobs,
  (SELECT count(*) FROM operations_recovery_state WHERE status = 'held')
    AS held_recovery_state,
  (SELECT count(*) FROM operations_recovery_state WHERE status = 'ready')
    AS ready_recovery_state
"""


class DrillError(RuntimeError):
    """A bounded restore-drill failure safe to show to an operator."""


class DrillInterrupted(DrillError):
    """A signal requested fail-closed cleanup."""


@dataclass(frozen=True, slots=True)
class DrillConfig:
    environment: str
    backup: Path
    backup_metadata: Path
    backup_sha256: str
    backup_metadata_sha256: str
    backup_captured_at: datetime
    backup_release_id: str
    evidence_dir: Path
    workspace_mode: str
    workspace_release_id: str
    expected_migration_head: str
    postgres_image: str
    application_image: str
    execute: bool
    acknowledge_isolated_target: bool
    reconcile_job_ids: tuple[UUID, ...]
    reconcile_outbox_event_ids: tuple[UUID, ...]
    reconcile_actor_person_id: UUID | None
    reconcile_tenant_id: UUID | None
    reconcile_reason: str | None
    acknowledge_reconciliation: bool


@dataclass(frozen=True, slots=True)
class SideEffectCounts:
    pending_outbox: int
    uncertain_external_jobs: int
    held_outbox: int
    held_external_jobs: int
    held_recovery_state: int
    ready_recovery_state: int

    def as_dict(self) -> dict[str, int]:
        return {
            "pending_outbox": self.pending_outbox,
            "uncertain_external_jobs": self.uncertain_external_jobs,
            "held_outbox": self.held_outbox,
            "held_external_jobs": self.held_external_jobs,
            "held_recovery_state": self.held_recovery_state,
            "ready_recovery_state": self.ready_recovery_state,
        }


@dataclass(frozen=True, slots=True)
class DisposableTarget:
    """Exact generated identities for one invocation."""

    run_id: str
    container: str
    init_container: str
    probe_container: str
    network: str
    volume: str
    database: str
    role: str
    password: str

    @property
    def label(self) -> str:
        return f"{LABEL_KEY}={self.run_id}"

    def cleanup(self) -> None:
        """Remove only exact-name resources carrying this invocation's label."""

        failures: list[str] = []
        for name in (self.probe_container, self.init_container, self.container):
            try:
                _remove_labeled_resource("container", name, self.run_id)
            except DrillError:
                failures.append(f"container:{name}")
        for kind, name in (("network", self.network), ("volume", self.volume)):
            try:
                _remove_labeled_resource(kind, name, self.run_id)
            except DrillError:
                failures.append(f"{kind}:{name}")
        if failures:
            raise DrillError("cleanup failed for exact labeled resources: " + ", ".join(failures))


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _workspace_root() -> Path:
    """Support both the source tree and the stripped application release."""

    script = Path(__file__).resolve()
    source_root = script.parents[3]
    if (source_root / "AGENTS.md").is_file() and (
        source_root / "db" / "migrations" / "versions"
    ).is_dir():
        return source_root
    release_root = script.parents[1]
    if (release_root / "compose.yaml").is_file() and (
        release_root / "scripts" / "restore-drill.py"
    ).is_file():
        return release_root
    raise DrillError("restore-drill workspace identity could not be established")


def _migration_head_from_source(source_root: Path) -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    migration_dir = source_root / "db" / "migrations" / "versions"
    for migration in sorted(migration_dir.glob("*.py")):
        if migration.name.startswith("_"):
            continue
        try:
            tree = ast.parse(migration.read_text(encoding="utf-8"), filename=str(migration))
        except (OSError, SyntaxError, UnicodeError) as error:
            raise DrillError("checked-in migration metadata is unreadable") from error
        metadata: dict[str, Any] = {}
        for node in tree.body:
            name: str | None = None
            value_node: ast.expr | None = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                value_node = node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    name = target.id
                    value_node = node.value
            if name not in {"revision", "down_revision"} or value_node is None:
                continue
            try:
                metadata[name] = ast.literal_eval(value_node)
            except (ValueError, SyntaxError) as error:
                raise DrillError("checked-in migration metadata is malformed") from error
        revision = metadata.get("revision")
        down_revision = metadata.get("down_revision")
        if "down_revision" not in metadata:
            raise DrillError("checked-in migration ancestry is missing")
        if not isinstance(revision, str) or revision in revisions:
            raise DrillError("checked-in migration revisions must be unique strings")
        revisions.add(revision)
        if down_revision is None:
            continue
        if isinstance(down_revision, str):
            parents.add(down_revision)
            continue
        if isinstance(down_revision, tuple) and all(
            isinstance(parent, str) for parent in down_revision
        ):
            parents.update(down_revision)
            continue
        raise DrillError("checked-in migration ancestry is malformed")
    if parents - revisions:
        raise DrillError("checked-in migration ancestry references an absent revision")
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise DrillError("checked-in migrations must have exactly one current head")
    return heads[0]


def _migration_head_from_release(release_root: Path) -> str:
    """Read the migration identity sealed into the reviewed release bundle."""

    manifest = release_root / "release-images.env"
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DrillError("release migration contract is unreadable") from error
    heads: list[str] = []
    for line in lines:
        key, separator, value = line.partition("=")
        if separator != "=" or ENVIRONMENT_NAME_PATTERN.fullmatch(key) is None:
            raise DrillError("release migration contract is malformed")
        if key == "AC_MIGRATION_HEAD":
            heads.append(value)
    if len(heads) != 1:
        raise DrillError("release must contain exactly one migration contract")
    return heads[0]


def _expected_migration_head(workspace_root: Path) -> str:
    """Bind source runs to the chain and release runs to the reviewed artifact."""

    if (workspace_root / "db" / "migrations" / "versions").is_dir():
        expected_head = _migration_head_from_source(workspace_root)
    else:
        expected_head = _migration_head_from_release(workspace_root)
    if MIGRATION_PATTERN.fullmatch(expected_head) is None:
        raise DrillError("restore-drill migration contract is malformed")
    return expected_head


def _release_id_from_source(source_root: Path) -> str:
    release_id = _run_process(
        ("git", "-C", str(source_root), "rev-parse", "--verify", "HEAD^{commit}"),
        "resolve source checkout release identity",
        timeout_seconds=DOCKER_TIMEOUT_SECONDS,
    )
    if RELEASE_PATTERN.fullmatch(release_id) is None:
        raise DrillError("source checkout release identity is malformed")
    return release_id


def _assert_clean_source_checkout(source_root: Path) -> None:
    """Reject source evidence that is not byte-bound to the claimed Git commit."""

    top_level = _run_process(
        ("git", "-C", str(source_root), "rev-parse", "--show-toplevel"),
        "resolve source checkout root",
        timeout_seconds=DOCKER_TIMEOUT_SECONDS,
    )
    try:
        resolved_top_level = Path(top_level).resolve(strict=True)
    except OSError as error:
        raise DrillError("source checkout root is unreadable") from error
    if resolved_top_level != source_root.resolve(strict=True):
        raise DrillError("restore drill must run from the exact Git worktree root")
    status = _run_process(
        (
            "git",
            "-C",
            str(source_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ),
        "verify clean source checkout",
        timeout_seconds=DOCKER_TIMEOUT_SECONDS,
    )
    if status:
        raise DrillError("source checkout has staged, unstaged, or untracked changes")


def _release_id_from_release(release_root: Path) -> str:
    marker = release_root / "RELEASE-COMMIT"
    if marker.is_symlink():
        raise DrillError("release identity marker must not be a symbolic link")
    try:
        marker_payload = marker.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise DrillError("release identity marker is unreadable") from error
    release_id = marker_payload.removesuffix("\n")
    if marker_payload != f"{release_id}\n" or RELEASE_PATTERN.fullmatch(release_id) is None:
        raise DrillError("release identity marker is malformed")

    manifest = release_root / "release-images.env"
    if manifest.is_symlink():
        raise DrillError("release image contract must not be a symbolic link")
    try:
        lines = manifest.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise DrillError("release image contract is unreadable") from error
    manifest_release_ids: list[str] = []
    for line in lines:
        key, separator, value = line.partition("=")
        if separator != "=" or ENVIRONMENT_NAME_PATTERN.fullmatch(key) is None:
            raise DrillError("release image contract is malformed")
        if key == "AC_RELEASE_ID":
            manifest_release_ids.append(value)
    if manifest_release_ids != [release_id]:
        raise DrillError("release identity marker does not match the image contract")
    return release_id


def _workspace_release_contract(workspace_root: Path) -> tuple[str, str, str]:
    """Return mode, release ID, and migration head from one exact workspace."""

    if (workspace_root / "db" / "migrations" / "versions").is_dir():
        mode = "source"
        _assert_clean_source_checkout(workspace_root)
        release_id = _release_id_from_source(workspace_root)
        migration_head = _migration_head_from_source(workspace_root)
        if _release_id_from_source(workspace_root) != release_id:
            raise DrillError("source checkout HEAD changed during release validation")
        _assert_clean_source_checkout(workspace_root)
    else:
        mode = "release"
        release_id = _release_id_from_release(workspace_root)
        migration_head = _migration_head_from_release(workspace_root)
    if MIGRATION_PATTERN.fullmatch(migration_head) is None:
        raise DrillError("restore-drill migration contract is malformed")
    return mode, release_id, migration_head


def _reject_broad_path(path: Path, *, label: str, workspace_root: Path) -> Path:
    resolved = path.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise DrillError(f"{label} must not be a filesystem root")
    if resolved == workspace_root or workspace_root in resolved.parents:
        raise DrillError(f"{label} must not be inside the application workspace")
    cwd = Path.cwd().resolve()
    if resolved == cwd or cwd in resolved.parents:
        raise DrillError(f"{label} must not be inside the current workspace")
    return resolved


def _validate_backup(value: str, *, workspace_root: Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise DrillError("backup must be an explicit absolute path")
    if raw.is_symlink():
        raise DrillError("backup must not be a symbolic link")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as error:
        raise DrillError("backup must resolve to an existing regular file") from error
    backup = _reject_broad_path(resolved, label="backup", workspace_root=workspace_root)
    if not backup.is_file() or not 5 <= backup.stat().st_size <= MAX_BACKUP_BYTES:
        raise DrillError("backup must be a non-empty regular custom-format pg_dump file")
    if "," in str(backup) or "\n" in str(backup) or "\r" in str(backup):
        raise DrillError("backup path contains characters unsafe for a Docker bind mount")
    with backup.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise DrillError("backup is not a custom-format pg_dump")
    return backup


def _validate_backup_metadata(
    value: str,
    *,
    backup: Path,
    environment: str,
    workspace_root: Path,
    expected_migration_head: str | None = None,
) -> tuple[Path, datetime, str, str, str]:
    raw = Path(value).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise DrillError("backup metadata must be an explicit non-symlink absolute path")
    try:
        metadata_path = raw.resolve(strict=True)
    except OSError as error:
        raise DrillError("backup metadata must resolve to an existing regular file") from error
    metadata_path = _reject_broad_path(
        metadata_path,
        label="backup metadata",
        workspace_root=workspace_root,
    )
    if (
        metadata_path != backup.with_suffix(".json")
        or not metadata_path.is_file()
        or metadata_path.stat().st_size > 64 * 1024
    ):
        raise DrillError("backup metadata must be the bounded JSON pair for the dump")
    backup_bytes = _read_stable_source(backup, max_bytes=MAX_BACKUP_BYTES)
    metadata_bytes = _read_stable_source(metadata_path, max_bytes=64 * 1024)
    backup_sha256 = hashlib.sha256(backup_bytes).hexdigest()
    metadata_sha256 = hashlib.sha256(metadata_bytes).hexdigest()
    try:
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DrillError("backup metadata is not valid UTF-8 JSON") from error
    expected_keys = {
        "artifact_type",
        "restic_tag",
        "environment",
        "release_id",
        "compose_project",
        "database_role",
        "format",
        "verification",
        "capture_started_at",
        "capture_completed_at",
        "captured_at",
        "captured_at_epoch_ns",
        "capture_clock",
        "dump_bytes",
        "dump_sha256",
    }
    parity_keys = expected_keys | {"row_counts"}
    versioned_keys = parity_keys | {"parity_contract", "migration_head"}
    if not isinstance(payload, dict) or set(payload) not in (
        expected_keys,
        parity_keys,
        versioned_keys,
    ):
        raise DrillError("backup metadata has an unexpected contract")
    expected_head = expected_migration_head or _expected_migration_head(workspace_root)
    tables = parity_tables_for_head(expected_head)
    contract = parity_contract_for_head(expected_head)
    if contract is not None:
        if (
            set(payload) != versioned_keys
            or payload.get("parity_contract") != contract
            or payload.get("migration_head") != expected_head
        ):
            raise DrillError("versioned backup requires its exact migration and parity contract")
    elif "parity_contract" in payload or "migration_head" in payload:
        raise DrillError("legacy backup must retain its legacy parity contract")
    if "row_counts" in payload:
        row_counts = payload["row_counts"]
        if (
            not isinstance(row_counts, dict)
            or set(row_counts) != set(tables)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in row_counts.values()
            )
        ):
            raise DrillError("backup metadata row-count parity is malformed")
    release_id = payload.get("release_id")
    expected_project = f"ac-application-{environment}"
    if (
        payload.get("artifact_type") != "authority-closers-postgresql-logical"
        or payload.get("restic_tag") != "authority-closers-postgres-logical"
        or payload.get("environment") != environment
        or payload.get("compose_project") != expected_project
        or payload.get("database_role") != "ac_backup"
        or payload.get("format") != "custom"
        or payload.get("verification") != "pg_restore --list"
        or payload.get("capture_clock") != "CLOCK_REALTIME"
        or not isinstance(release_id, str)
        or re.fullmatch(r"[0-9a-f]{40}", release_id) is None
    ):
        raise DrillError("backup metadata identity does not match the selected environment")
    dump_bytes = payload.get("dump_bytes")
    captured_at_epoch_ns = payload.get("captured_at_epoch_ns")
    if (
        isinstance(dump_bytes, bool)
        or not isinstance(dump_bytes, int)
        or dump_bytes != len(backup_bytes)
        or isinstance(captured_at_epoch_ns, bool)
        or not isinstance(captured_at_epoch_ns, int)
        or captured_at_epoch_ns <= 0
        or payload.get("dump_sha256") != backup_sha256
    ):
        raise DrillError("backup metadata size or digest does not match the dump")
    try:
        started_at = _parse_timestamp(str(payload["capture_started_at"]))
        completed_at = _parse_timestamp(str(payload["capture_completed_at"]))
        captured_at = _parse_timestamp(str(payload["captured_at"]))
    except argparse.ArgumentTypeError as error:
        raise DrillError("backup metadata timestamps are invalid") from error
    if completed_at != captured_at or started_at > completed_at or captured_at > _now():
        raise DrillError("backup metadata timestamps are inconsistent")
    return metadata_path, captured_at, release_id, backup_sha256, metadata_sha256


def _path_is_root_owned(path: Path) -> bool:
    if os.name != "posix":
        return True
    try:
        return path.lstat().st_uid == 0
    except OSError as error:
        raise DrillError("stable restore input ownership could not be verified") from error


def _prepare_stable_input_root(root: Path) -> None:
    if os.name == "posix":
        if not hasattr(os, "O_NOFOLLOW"):
            raise DrillError("the Linux no-follow filesystem primitive is unavailable")
        get_effective_user_id = getattr(os, "geteuid", None)
        if not callable(get_effective_user_id) or get_effective_user_id() != 0:
            raise DrillError("executed restore drills require root-owned stable input staging")
    for ancestor in (root, *root.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise DrillError("stable restore input root has a symbolic-link ancestor")
        if ancestor.exists() and os.name == "posix" and not _path_is_root_owned(ancestor):
            raise DrillError("stable restore input root has a non-root-owned ancestor")
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        metadata = root.lstat()
    except OSError as error:
        raise DrillError("stable restore input root could not be prepared") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or root.is_symlink()
        or not _path_is_root_owned(root)
        or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o700)
    ):
        raise DrillError("stable restore input root is unsafe")


def _create_stable_input_dir(root: Path) -> Path:
    _prepare_stable_input_root(root)
    for _attempt in range(8):
        candidate = root / f".input-{secrets.token_hex(12)}"
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        except OSError as error:
            raise DrillError("stable restore input directory could not be created") from error
        try:
            candidate.chmod(0o700)
            metadata = candidate.lstat()
            if (
                candidate.parent != root
                or STABLE_INPUT_DIR_PATTERN.fullmatch(candidate.name) is None
                or candidate.is_symlink()
                or not stat.S_ISDIR(metadata.st_mode)
                or not _path_is_root_owned(candidate)
                or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o700)
            ):
                raise DrillError("stable restore input directory is unsafe")
            return candidate
        except BaseException:
            # The generated directory is still empty here. Remove it before
            # propagating any validation, filesystem, interrupt, or signal
            # exception so creation cannot leak a staging directory.
            _remove_stable_input_dir(candidate, root)
            raise
    raise DrillError("stable restore input directory identity is ambiguous")


def _read_stable_source(path: Path, *, max_bytes: int) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= max_bytes:
            raise DrillError("validated restore input source is unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise DrillError("validated restore input source was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    except DrillError:
        raise
    except OSError as error:
        raise DrillError("validated restore input source could not be copied") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise DrillError("validated restore input source changed during copy")
    return b"".join(chunks)


def _write_private_input(path: Path, data: bytes, *, mode: int) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        written = 0
        while written < len(data):
            written += os.write(descriptor, data[written:])
        os.fsync(descriptor)
    except OSError as error:
        raise DrillError("stable restore input could not be written") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not _path_is_root_owned(path)
        or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != mode)
    ):
        raise DrillError("stable restore input file is unsafe")


def _remove_stable_input_dir(path: Path, root: Path) -> None:
    if (
        path.parent != root
        or STABLE_INPUT_DIR_PATTERN.fullmatch(path.name) is None
        or path.is_symlink()
        or not path.is_dir()
        or not _path_is_root_owned(path)
    ):
        raise DrillError("refusing to remove an unsafe stable restore input directory")
    expected_names = {"backup.dump", "backup.json"}
    entries = tuple(path.iterdir())
    if {entry.name for entry in entries} - expected_names:
        raise DrillError("stable restore input directory contains an unexpected entry")
    for entry in entries:
        metadata = entry.lstat()
        if (
            entry.parent != path
            or entry.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or not _path_is_root_owned(entry)
        ):
            raise DrillError("stable restore input cleanup found an unsafe entry")
        entry.unlink()
    path.rmdir()


@contextmanager
def _stable_restore_inputs(
    config: DrillConfig,
    *,
    root: Path = STABLE_INPUT_ROOT,
) -> Iterator[DrillConfig]:
    previous_handlers: dict[int, Any] = {
        int(signum): signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    stable_dir: Path | None = None
    # Do not allow an asynchronous exception in the few instructions between
    # directory creation and registration of the cleanup scope. The reviewed
    # handlers are restored immediately after the directory is captured.
    _ignore_cleanup_signals()
    try:
        stable_dir = _create_stable_input_dir(root)
        _restore_signal_handlers(previous_handlers)
        dump_data = _read_stable_source(config.backup, max_bytes=MAX_BACKUP_BYTES)
        metadata_data = _read_stable_source(config.backup_metadata, max_bytes=64 * 1024)
        if (
            hashlib.sha256(dump_data).hexdigest() != config.backup_sha256
            or hashlib.sha256(metadata_data).hexdigest() != config.backup_metadata_sha256
        ):
            raise DrillError("validated restore input identity changed before stable copy")
        stable_backup = stable_dir / "backup.dump"
        stable_metadata = stable_dir / "backup.json"
        # The root-owned 0700 parent prevents host traversal. The dump is
        # group-readable only so the isolated PostgreSQL container can receive
        # that exact group as a supplemental read-only group. Metadata remains
        # root-only and is never mounted into the container.
        _write_private_input(stable_backup, dump_data, mode=0o640)
        _write_private_input(stable_metadata, metadata_data, mode=0o600)
        if set(stable_dir.iterdir()) != {stable_backup, stable_metadata}:
            raise DrillError("stable restore input directory has an unexpected contract")
        workspace_root = _workspace_root()
        verified_backup = _validate_backup(str(stable_backup), workspace_root=workspace_root)
        (
            verified_metadata,
            captured_at,
            release_id,
            backup_sha256,
            metadata_sha256,
        ) = _validate_backup_metadata(
            str(stable_metadata),
            backup=verified_backup,
            environment=config.environment,
            workspace_root=workspace_root,
            expected_migration_head=config.expected_migration_head,
        )
        if (
            captured_at != config.backup_captured_at
            or release_id != config.backup_release_id
            or backup_sha256 != config.backup_sha256
            or metadata_sha256 != config.backup_metadata_sha256
        ):
            raise DrillError("stable restore inputs changed the validated backup identity")
        yield replace(
            config,
            backup=verified_backup,
            backup_metadata=verified_metadata,
        )
    finally:
        _ignore_cleanup_signals()
        try:
            if stable_dir is not None:
                _remove_stable_input_dir(stable_dir, root)
        finally:
            _restore_signal_handlers(previous_handlers)


def _validate_evidence_dir(value: str, *, workspace_root: Path) -> Path:
    """Validate without creating; the execute preflight creates it later."""

    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise DrillError("evidence directory must be an explicit absolute path")
    if raw.exists() or raw.is_symlink():
        raise DrillError("evidence directory must not already exist")
    if raw.name in {"", ".", ".."} or "\n" in raw.name or "\r" in raw.name:
        raise DrillError("evidence directory name is unsafe")
    if raw.parent.is_symlink():
        raise DrillError("evidence directory parent must not be a symbolic link")
    try:
        parent = raw.parent.resolve(strict=True)
    except OSError as error:
        raise DrillError("evidence directory parent must already exist") from error
    if not parent.is_dir():
        raise DrillError("evidence directory parent must be a directory")
    candidate = parent / raw.name
    return _reject_broad_path(
        candidate,
        label="evidence directory",
        workspace_root=workspace_root,
    )


def _validate_postgres_image(value: str) -> str:
    image = value.strip()
    if POSTGRES_IMAGE_PATTERN.fullmatch(image) is None:
        raise DrillError("PostgreSQL image must be postgres pinned by sha256 digest")
    return image


def _validate_application_image(value: str) -> str:
    image = value.strip()
    if APPLICATION_IMAGE_PATTERN.fullmatch(image) is None:
        raise DrillError("application image must be an exact sha256:<64> local image ID")
    return image


def _short_token() -> str:
    return secrets.token_hex(6)


def _target_for(token: str) -> DisposableTarget:
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise DrillError("internal target token is invalid")
    base = f"ac-restore-drill-{token}"
    return DisposableTarget(
        run_id=token,
        container=base,
        init_container=f"{base}-init",
        probe_container=f"{base}-probe",
        network=base,
        volume=base,
        database=f"ac_restore_drill_{token}",
        role=f"ac_restore_owner_{token}",
        password=secrets.token_urlsafe(36),
    )


def _validate_target_names(target: DisposableTarget) -> None:
    if TOKEN_PATTERN.fullmatch(target.run_id) is None:
        raise DrillError("generated run identifier failed the safety check")
    if BASE_NAME_PATTERN.fullmatch(target.container) is None:
        raise DrillError("generated target container name failed the safety check")
    if target.init_container != f"{target.container}-init":
        raise DrillError("generated volume initializer name failed the safety check")
    if target.probe_container != f"{target.container}-probe":
        raise DrillError("generated application probe name failed the safety check")
    if target.network != target.container or target.volume != target.container:
        raise DrillError("generated Docker resource identities are inconsistent")
    if DATABASE_NAME_PATTERN.fullmatch(target.database) is None:
        raise DrillError("generated database identity failed the safety check")
    if ROLE_NAME_PATTERN.fullmatch(target.role) is None:
        raise DrillError("generated database role identity failed the safety check")


def _invoke_process(
    command: Sequence[str],
    step: str,
    *,
    timeout_seconds: int,
    env_updates: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if env_updates:
        environment.update(env_updates)
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise DrillError(f"{step} timed out after {timeout_seconds} seconds") from error
    except OSError as error:
        raise DrillError(f"{step} could not start") from error


def _run_process(
    command: Sequence[str],
    step: str,
    *,
    timeout_seconds: int,
    env_updates: Mapping[str, str] | None = None,
) -> str:
    completed = _invoke_process(
        command,
        step,
        timeout_seconds=timeout_seconds,
        env_updates=env_updates,
    )
    if completed.returncode != 0:
        raise DrillError(f"{step} failed (exit {completed.returncode})")
    return completed.stdout.strip()


def _run_docker(
    args: Sequence[str],
    step: str,
    *,
    timeout_seconds: int = DOCKER_TIMEOUT_SECONDS,
    env_updates: Mapping[str, str] | None = None,
) -> str:
    return _run_docker_output(
        args,
        step,
        timeout_seconds=timeout_seconds,
        env_updates=env_updates,
    ).strip()


def _run_docker_output(
    args: Sequence[str],
    step: str,
    *,
    timeout_seconds: int = DOCKER_TIMEOUT_SECONDS,
    env_updates: Mapping[str, str] | None = None,
) -> str:
    completed = _invoke_process(
        ("docker", *args),
        step,
        timeout_seconds=timeout_seconds,
        env_updates=env_updates,
    )
    if completed.returncode != 0:
        raise DrillError(f"{step} failed (exit {completed.returncode})")
    return completed.stdout


def _docker_inspect_optional(kind: str, name: str) -> dict[str, Any] | None:
    if kind not in {"container", "network", "volume"}:
        raise DrillError("internal Docker resource kind is invalid")
    completed = _invoke_process(
        ("docker", kind, "inspect", name),
        f"inspect exact {kind}",
        timeout_seconds=DOCKER_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        safe_error = completed.stderr.lower()
        if "no such" in safe_error or "not found" in safe_error:
            return None
        raise DrillError(f"inspect exact {kind} failed (exit {completed.returncode})")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DrillError(f"inspect exact {kind} returned invalid JSON") from error
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise DrillError(f"inspect exact {kind} returned an unexpected shape")
    return payload[0]


def _resource_labels(kind: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if kind == "container":
        config = payload.get("Config")
        if not isinstance(config, Mapping):
            return {}
        labels = config.get("Labels")
    else:
        labels = payload.get("Labels")
    return labels if isinstance(labels, Mapping) else {}


def _remove_labeled_resource(kind: str, name: str, run_id: str) -> None:
    payload = _docker_inspect_optional(kind, name)
    if payload is None:
        return
    if _resource_labels(kind, payload).get(LABEL_KEY) != run_id:
        raise DrillError(f"refusing to remove exact {kind} without the invocation label")
    args = ("container", "rm", "--force", name) if kind == "container" else (kind, "rm", name)
    _run_docker(args, f"remove exact labeled {kind}")


def _preflight(target: DisposableTarget, config: DrillConfig) -> None:
    """Complete identity checks before persistent target/evidence mutation."""

    _validate_target_names(target)
    _run_docker(("version", "--format", "{{.Server.Version}}"), "verify Docker server")
    image_id = _run_docker(
        ("image", "inspect", "--format", "{{.Id}}", config.application_image),
        "verify local application image",
    )
    if image_id != config.application_image:
        raise DrillError("local application image identity does not match the exact image ID")
    _run_docker(
        ("image", "inspect", "--format", "{{.Id}}", config.postgres_image),
        "verify local PostgreSQL image",
    )
    for kind, name in (
        ("container", target.container),
        ("container", target.init_container),
        ("container", target.probe_container),
        ("network", target.network),
        ("volume", target.volume),
    ):
        if _docker_inspect_optional(kind, name) is not None:
            raise DrillError(f"generated {kind} name already exists; refusing to reuse it")
    image_release_id, image_migration_head = _application_image_contract(
        config.application_image,
        target,
    )
    if (
        image_release_id != config.backup_release_id
        or image_release_id != config.workspace_release_id
    ):
        raise DrillError(
            "application image release marker does not match the backup and workspace release"
        )
    if image_migration_head != config.expected_migration_head:
        raise DrillError("application image migration head does not match the workspace head")


def _application_image_contract(image: str, target: DisposableTarget) -> tuple[str, str]:
    def constrained_run(name: str) -> tuple[str, ...]:
        return (
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            name,
            "--label",
            target.label,
            "--network",
            "none",
            "--read-only",
            "--security-opt",
            "no-new-privileges:true",
            "--cap-drop",
            "ALL",
        )

    previous_handlers = _install_signal_handlers()
    try:
        release_output = _run_docker_output(
            (
                *constrained_run(target.probe_container),
                "--entrypoint",
                "/bin/sh",
                image,
                "-euc",
                "cat /app/.ac-release-id",
            ),
            "read exact application image release marker",
        )
        release_match = re.fullmatch(r"([0-9a-f]{40})\n", release_output)
        if release_match is None:
            raise DrillError("application image release marker is malformed")
        release_id = release_match.group(1)
        heads_output = _run_docker_output(
            (
                *constrained_run(target.init_container),
                "--entrypoint",
                "alembic",
                image,
                "heads",
            ),
            "read exact application image migration head",
        )
        head_lines = heads_output.splitlines()
        if len(head_lines) != 1 or heads_output != f"{head_lines[0]}\n":
            raise DrillError("application image must report exactly one migration head")
        match = re.fullmatch(r"([0-9]{8}_[0-9]{4})[ \t]+\(head\)", head_lines[0])
        if match is None:
            raise DrillError("application image migration head is malformed")
        return release_id, match.group(1)
    finally:
        _ignore_cleanup_signals()
        cleanup_failures: list[str] = []
        try:
            for name in (target.probe_container, target.init_container):
                try:
                    _remove_labeled_resource("container", name, target.run_id)
                except DrillError:
                    cleanup_failures.append(name)
        finally:
            _restore_signal_handlers(previous_handlers)
        if cleanup_failures:
            raise DrillError(
                "application image attestation cleanup failed for exact containers: "
                + ", ".join(cleanup_failures)
            )


def _volume_init_command(target: DisposableTarget, image: str) -> tuple[str, ...]:
    return (
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        target.init_container,
        "--label",
        target.label,
        "--network",
        "none",
        "--read-only",
        "--user",
        "0:0",
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "CHOWN",
        "--pids-limit",
        "64",
        "--cpus",
        "0.50",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--shm-size",
        "16m",
        "--mount",
        f"type=volume,source={target.volume},destination=/var/lib/postgresql",
        "--entrypoint",
        "/bin/sh",
        image,
        "-euc",
        # PostgreSQL 18 initializes this mount point as 999:999:1777.  The
        # initializer deliberately has CAP_CHOWN but not CAP_FOWNER, so first
        # pivot ownership to its effective uid, normalize the mode as owner,
        # and then hand the directory back to PostgreSQL.  This keeps the
        # capability set narrower than adding FOWNER.
        "chown 0:0 /var/lib/postgresql\n"
        "chmod 0700 /var/lib/postgresql\n"
        "chown 999:999 /var/lib/postgresql\n"
        "stat -c '%u:%g:%a' /var/lib/postgresql | grep -qx '999:999:700'",
    )


def _postgres_run_command(
    target: DisposableTarget,
    backup: Path,
    image: str,
) -> tuple[str, ...]:
    backup_group_id = backup.stat().st_gid
    if isinstance(backup_group_id, bool) or not 0 <= backup_group_id <= 4_294_967_295:
        raise DrillError("stable restore input group identity is invalid")
    return (
        "run",
        "--detach",
        "--pull",
        "never",
        "--name",
        target.container,
        "--hostname",
        target.container,
        "--label",
        target.label,
        "--network",
        target.network,
        "--network-alias",
        target.container,
        "--read-only",
        "--user",
        "999:999",
        "--group-add",
        str(backup_group_id),
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "256",
        "--cpus",
        "2.00",
        "--memory",
        "2g",
        "--memory-swap",
        "2g",
        "--shm-size",
        "256m",
        "--stop-timeout",
        "30",
        "--mount",
        f"type=volume,source={target.volume},destination=/var/lib/postgresql",
        "--mount",
        f"type=bind,source={backup},destination=/restore/backup.dump,readonly",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=67108864,uid=999,gid=999,mode=0700",
        "--tmpfs",
        "/var/run/postgresql:rw,noexec,nosuid,nodev,size=16777216,uid=999,gid=999,mode=0700",
        "--env",
        "POSTGRES_DB",
        "--env",
        "POSTGRES_USER",
        "--env",
        "POSTGRES_PASSWORD",
        "--env",
        "POSTGRES_INITDB_ARGS",
        image,
    )


def _probe_command(
    target: DisposableTarget,
    application_image: str,
    action_args: Sequence[str],
    *,
    operations_tenant_id: UUID | None = None,
) -> tuple[str, ...]:
    command = [
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        target.probe_container,
        "--hostname",
        target.probe_container,
        "--label",
        target.label,
        "--network",
        target.network,
        "--read-only",
        "--user",
        "10001:10001",
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "128",
        "--cpus",
        "1.00",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--shm-size",
        "64m",
        "--stop-timeout",
        "15",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=33554432,uid=10001,gid=10001,mode=0700",
        "--env",
        "AC_RESTORE_DRILL_DATABASE_URL",
        "--env",
        "AC_RESTORE_DRILL_ACKNOWLEDGE",
    ]
    if operations_tenant_id is not None:
        command.extend(("--env", "AC_OPERATIONS_TENANT_ID"))
    command.extend(
        (
            "--entrypoint",
            "python",
            application_image,
            "-m",
            "ac_platform.recovery.restore_drill_probe",
            *action_args,
        )
    )
    return tuple(command)


def _create_target(target: DisposableTarget, config: DrillConfig) -> None:
    _run_docker(
        (
            "network",
            "create",
            "--driver",
            "bridge",
            "--internal",
            "--label",
            target.label,
            target.network,
        ),
        "create isolated internal network",
    )
    _run_docker(
        ("volume", "create", "--label", target.label, target.volume),
        "create isolated state volume",
    )
    _run_docker(
        _volume_init_command(target, config.postgres_image),
        "initialize exact PostgreSQL volume ownership",
        timeout_seconds=DOCKER_TIMEOUT_SECONDS,
    )
    _run_docker(
        _postgres_run_command(target, config.backup, config.postgres_image),
        "create disposable PostgreSQL target",
        env_updates={
            "POSTGRES_DB": target.database,
            "POSTGRES_USER": target.role,
            "POSTGRES_PASSWORD": target.password,
            "POSTGRES_INITDB_ARGS": (
                "--auth-host=scram-sha-256 --auth-local=scram-sha-256 --data-checksums"
            ),
        },
    )
    _wait_for_database(target)


def _docker_exec(
    target: DisposableTarget,
    args: Sequence[str],
    step: str,
    *,
    timeout_seconds: int = DOCKER_TIMEOUT_SECONDS,
    env_updates: Mapping[str, str] | None = None,
) -> str:
    command: list[str] = ["exec"]
    if env_updates:
        for name in sorted(env_updates):
            if ENVIRONMENT_NAME_PATTERN.fullmatch(name) is None:
                raise DrillError("internal Docker environment name is invalid")
            command.extend(("--env", name))
    command.append(target.container)
    command.extend(args)
    return _run_docker(
        command,
        step,
        timeout_seconds=timeout_seconds,
        env_updates=env_updates,
    )


def _query(target: DisposableTarget, query: str, step: str) -> str:
    return _docker_exec(
        target,
        (
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atq",
            "-h",
            "127.0.0.1",
            "-U",
            target.role,
            "-d",
            target.database,
            "-c",
            query,
        ),
        step,
        timeout_seconds=QUERY_TIMEOUT_SECONDS,
        env_updates={"PGPASSWORD": target.password},
    )


def _wait_for_database(target: DisposableTarget) -> None:
    deadline = time.monotonic() + DATABASE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if (
                _query(target, "SELECT current_database()", "database readiness probe")
                == target.database
            ):
                return
        except DrillError:
            pass
        time.sleep(2)
    raise DrillError("disposable PostgreSQL target did not become ready")


def _restore_dump(target: DisposableTarget) -> None:
    _docker_exec(
        target,
        ("pg_restore", "--list", "/restore/backup.dump"),
        "validate custom-format pg_dump",
        timeout_seconds=RESTORE_LIST_TIMEOUT_SECONDS,
    )
    _docker_exec(
        target,
        (
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "--host",
            "127.0.0.1",
            "--username",
            target.role,
            "--dbname",
            target.database,
            "/restore/backup.dump",
        ),
        "restore custom-format pg_dump",
        timeout_seconds=RESTORE_TIMEOUT_SECONDS,
        env_updates={"PGPASSWORD": target.password},
    )


def _verify_target_identity(target: DisposableTarget) -> dict[str, str]:
    values = _query(
        target,
        "SELECT current_database(), current_user, current_setting('server_version_num'), "
        "current_setting('server_version')",
        "verify PostgreSQL target identity",
    ).split("|")
    if len(values) != 4 or values[0] != target.database or values[1] != target.role:
        raise DrillError("restored target database identity does not match this invocation")
    if not values[2].startswith("18"):
        raise DrillError("restored target is not PostgreSQL 18")
    return {
        "database": values[0],
        "role": values[1],
        "server_version_num": values[2],
        "server_version": values[3],
    }


def _schema_and_migration(target: DisposableTarget, expected_head: str) -> dict[str, Any]:
    tables = parity_tables_for_head(expected_head)
    actual_tables = set(
        filter(
            None,
            _query(
                target,
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename",
                "inspect restored schema",
            ).splitlines(),
        )
    )
    missing = sorted(set(tables) - actual_tables)
    if missing:
        raise DrillError(f"restored schema is missing {len(missing)} canonical tables")
    versions = _query(
        target,
        "SELECT version_num FROM alembic_version ORDER BY version_num",
        "verify migration identity",
    ).splitlines()
    if versions != [expected_head]:
        raise DrillError("restored migration identity does not match the expected head")
    return {
        "expected_migration_head": expected_head,
        "actual_migration_versions": versions,
        "canonical_tables_checked": len(tables),
        "extra_public_tables": len(actual_tables - set(tables)),
    }


def _row_counts(target: DisposableTarget, expected_head: str) -> dict[str, int]:
    tables = parity_tables_for_head(expected_head)
    query = " UNION ALL ".join(
        f"SELECT '{table}', count(*)::bigint FROM \"{table}\"" for table in tables
    )
    result: dict[str, int] = {}
    for line in _query(target, query, "collect representative row counts").splitlines():
        values = line.split("|", 1)
        if len(values) != 2 or values[0] not in tables or values[0] in result:
            raise DrillError("representative row counts returned an unexpected shape")
        try:
            result[values[0]] = int(values[1])
        except ValueError as error:
            raise DrillError("representative row count is invalid") from error
    if set(result) != set(tables) or any(value < 0 for value in result.values()):
        raise DrillError("representative row counts are incomplete")
    return result


def _verify_versioned_backup_parity(config: DrillConfig, actual: Mapping[str, int]) -> None:
    contract = parity_contract_for_head(config.expected_migration_head)
    if contract is None:
        return
    tables = parity_tables_for_head(config.expected_migration_head)
    # These inputs have already been copied privately and hash/contract-checked.
    try:
        metadata = json.loads(config.backup_metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DrillError("versioned backup metadata is unreadable for parity") from error
    if (
        not isinstance(metadata, dict)
        or metadata.get("parity_contract") != contract
        or metadata.get("migration_head") != config.expected_migration_head
        or set(actual) != set(tables)
        or dict(actual) != metadata.get("row_counts")
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in actual.values()
        )
    ):
        raise DrillError("restored versioned row-count parity failed")


def _invariants(target: DisposableTarget) -> dict[str, int]:
    query = """
SELECT
  (SELECT count(*) FROM operations_recovery_state WHERE id <> 1)
    AS recovery_non_singleton,
  (SELECT count(*) FROM operations_recovery_state WHERE generation < 1)
    AS recovery_bad_generation,
  (SELECT count(*) FROM outbox_events
   WHERE status = 'held' AND (held_at IS NULL OR hold_reason IS NULL)) AS outbox_bad_held,
  (SELECT count(*) FROM outbox_events
   WHERE status = 'published' AND published_at IS NULL) AS outbox_bad_published,
  (SELECT count(*) FROM jobs
   WHERE status = 'held' AND (held_at IS NULL OR hold_reason IS NULL)) AS jobs_bad_held,
  (SELECT count(*) FROM jobs
   WHERE status = 'leased' AND (lease_token IS NULL OR leased_until IS NULL)) AS jobs_bad_lease,
  (SELECT count(*) FROM jobs
   WHERE external_side_effect AND recovery_generation < 1) AS jobs_bad_generation,
  (SELECT count(*) FROM jobs
   WHERE status = 'succeeded' AND external_side_effect AND provider_receipt IS NULL)
    AS jobs_missing_receipt
"""
    names = (
        "recovery_non_singleton",
        "recovery_bad_generation",
        "outbox_bad_held",
        "outbox_bad_published",
        "jobs_bad_held",
        "jobs_bad_lease",
        "jobs_bad_generation",
        "jobs_missing_receipt",
    )
    raw_values = _query(target, query, "verify restored invariants").split("|")
    if len(raw_values) != len(names):
        raise DrillError("restored invariant query returned an unexpected shape")
    try:
        result = {name: int(value) for name, value in zip(names, raw_values, strict=True)}
    except ValueError as error:
        raise DrillError("restored invariant query returned an invalid count") from error
    if any(result.values()):
        raise DrillError("restored representative invariants failed")
    return result


def _side_effect_counts(target: DisposableTarget) -> SideEffectCounts:
    values = _query(
        target,
        SIDE_EFFECT_COUNTS_QUERY,
        "collect side-effect hold counts",
    ).split("|")
    if len(values) != 6:
        raise DrillError("side-effect count query returned an unexpected shape")
    try:
        counts = tuple(int(value) for value in values)
    except ValueError as error:
        raise DrillError("side-effect count query returned an invalid count") from error
    if any(value < 0 for value in counts):
        raise DrillError("side-effect count query returned a negative count")
    return SideEffectCounts(*counts)


def _helper_database_url(target: DisposableTarget) -> str:
    return (
        f"postgresql+psycopg://{quote(target.role, safe='')}:"
        f"{quote(target.password, safe='')}@{target.container}:5432/{target.database}"
    )


def _run_probe(
    target: DisposableTarget,
    application_image: str,
    action_args: Sequence[str],
    step: str,
    *,
    operations_tenant_id: UUID | None = None,
) -> dict[str, Any]:
    environment = {
        "AC_RESTORE_DRILL_DATABASE_URL": _helper_database_url(target),
        "AC_RESTORE_DRILL_ACKNOWLEDGE": PROBE_ACKNOWLEDGEMENT,
    }
    if operations_tenant_id is not None:
        environment["AC_OPERATIONS_TENANT_ID"] = str(operations_tenant_id)
    output = _run_docker(
        _probe_command(
            target,
            application_image,
            action_args,
            operations_tenant_id=operations_tenant_id,
        ),
        step,
        timeout_seconds=HELPER_TIMEOUT_SECONDS,
        env_updates=environment,
    )
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise DrillError("application recovery probe did not emit one safe JSON result")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise DrillError("application recovery probe returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise DrillError("application recovery probe returned an unexpected shape")
    return payload


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise DrillError(f"{label} returned an unexpected safe JSON shape")


def _nonnegative_int(value: Any, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DrillError(f"{label} returned an invalid integer")
    if value < (1 if positive else 0):
        raise DrillError(f"{label} returned an out-of-range integer")
    return value


def _validate_mark_probe(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_exact_keys(
        payload,
        {"action", "restore_marker", "worker_hold_proof"},
        "mark-and-prove probe",
    )
    if payload["action"] != "mark-and-prove":
        raise DrillError("mark-and-prove probe returned the wrong action")
    marker_raw = payload["restore_marker"]
    proof_raw = payload["worker_hold_proof"]
    if not isinstance(marker_raw, Mapping) or not isinstance(proof_raw, Mapping):
        raise DrillError("mark-and-prove probe returned an unexpected nested shape")
    _require_exact_keys(
        marker_raw,
        {"generation", "status", "held_outbox", "held_jobs"},
        "restore marker",
    )
    _require_exact_keys(
        proof_raw,
        {"worker_ready", "run_once_rejected", "provider_calls"},
        "worker hold proof",
    )
    marker = {
        "generation": _nonnegative_int(
            marker_raw["generation"],
            "restore generation",
            positive=True,
        ),
        "status": marker_raw["status"],
        "held_outbox": _nonnegative_int(marker_raw["held_outbox"], "held outbox count"),
        "held_jobs": _nonnegative_int(marker_raw["held_jobs"], "held job count"),
    }
    proof = {
        "worker_ready": proof_raw["worker_ready"],
        "run_once_rejected": proof_raw["run_once_rejected"],
        "provider_calls": _nonnegative_int(proof_raw["provider_calls"], "provider call count"),
    }
    if marker["status"] != "held":
        raise DrillError("sanctioned restore marker did not hold recovery state")
    if proof != {
        "worker_ready": False,
        "run_once_rejected": True,
        "provider_calls": 0,
    }:
        raise DrillError("worker no-provider-call proof failed")
    return marker, proof


def _assert_hold_transition(
    before: SideEffectCounts,
    after: SideEffectCounts,
    marker: Mapping[str, Any],
) -> None:
    expected_held_outbox = before.held_outbox + before.pending_outbox
    expected_held_jobs = before.held_external_jobs + before.uncertain_external_jobs
    if marker["held_outbox"] != before.pending_outbox:
        raise DrillError("restore marker did not report the exact pending outbox transition")
    if marker["held_jobs"] != expected_held_jobs:
        raise DrillError("restore marker did not report the exact external job transition")
    if (
        after.pending_outbox != 0
        or after.uncertain_external_jobs != 0
        or after.held_outbox != expected_held_outbox
        or after.held_external_jobs != expected_held_jobs
        or after.held_recovery_state != 1
        or after.ready_recovery_state != 0
    ):
        raise DrillError("sanctioned restore hold transition was not exact")


def _reconciliation_action_args(config: DrillConfig) -> tuple[str, ...]:
    actor = config.reconcile_actor_person_id
    tenant = config.reconcile_tenant_id
    reason = config.reconcile_reason
    if actor is None or tenant is None or reason is None:
        raise DrillError("selected reconciliation requires actor, tenant, and reason")
    args: list[str] = ["reconcile-selected"]
    for job_id in config.reconcile_job_ids:
        args.extend(("--job-id", str(job_id)))
    for event_id in config.reconcile_outbox_event_ids:
        args.extend(("--outbox-event-id", str(event_id)))
    args.extend(
        (
            "--actor-person-id",
            str(actor),
            "--tenant-id",
            str(tenant),
            "--reason",
            reason,
            "--acknowledge-selected-reconciliation",
        )
    )
    return tuple(args)


def _validate_reconcile_probe(
    payload: Mapping[str, Any],
    config: DrillConfig,
    expected_generation: int,
) -> dict[str, Any]:
    _require_exact_keys(
        payload,
        {"action", "job_ids", "outbox_event_ids", "recovery_state"},
        "selected reconciliation probe",
    )
    if payload["action"] != "reconcile-selected":
        raise DrillError("selected reconciliation probe returned the wrong action")
    raw_jobs = payload["job_ids"]
    raw_events = payload["outbox_event_ids"]
    recovery = payload["recovery_state"]
    if not isinstance(raw_jobs, list) or not isinstance(raw_events, list):
        raise DrillError("selected reconciliation probe returned invalid ID sets")
    if not isinstance(recovery, Mapping):
        raise DrillError("selected reconciliation probe returned invalid recovery state")
    _require_exact_keys(recovery, {"generation", "status"}, "reconciliation recovery state")
    try:
        job_ids = tuple(UUID(value) for value in raw_jobs if isinstance(value, str))
        event_ids = tuple(UUID(value) for value in raw_events if isinstance(value, str))
    except ValueError as error:
        raise DrillError("selected reconciliation probe returned malformed IDs") from error
    if len(job_ids) != len(raw_jobs) or set(job_ids) != set(config.reconcile_job_ids):
        raise DrillError("selected reconciliation changed the requested job set")
    if len(event_ids) != len(raw_events) or set(event_ids) != set(
        config.reconcile_outbox_event_ids
    ):
        raise DrillError("selected reconciliation changed the requested outbox set")
    generation = _nonnegative_int(
        recovery["generation"],
        "reconciliation recovery generation",
        positive=True,
    )
    if generation != expected_generation or recovery["status"] not in {"held", "ready"}:
        raise DrillError("selected reconciliation returned invalid recovery state")
    return {
        "requested": True,
        "job_ids": [str(value) for value in config.reconcile_job_ids],
        "outbox_event_ids": [str(value) for value in config.reconcile_outbox_event_ids],
        "recovery_state": {"generation": generation, "status": recovery["status"]},
    }


def _assert_reconciliation_transition(
    before: SideEffectCounts,
    after: SideEffectCounts,
    config: DrillConfig,
) -> None:
    released_jobs = len(config.reconcile_job_ids)
    released_events = len(config.reconcile_outbox_event_ids)
    if (
        after.pending_outbox != before.pending_outbox + released_events
        or after.uncertain_external_jobs != before.uncertain_external_jobs + released_jobs
        or after.held_outbox != before.held_outbox - released_events
        or after.held_external_jobs != before.held_external_jobs - released_jobs
    ):
        raise DrillError("selected reconciliation did not release exactly the selected set")
    remaining_held = after.held_outbox + after.held_external_jobs
    expected_held_state = 1 if remaining_held else 0
    expected_ready_state = 0 if remaining_held else 1
    if (
        after.held_recovery_state != expected_held_state
        or after.ready_recovery_state != expected_ready_state
    ):
        raise DrillError("selected reconciliation left an inconsistent recovery gate")


def _validate_reconciliation_args(args: argparse.Namespace) -> None:
    job_ids = tuple(args.reconcile_job_id or ())
    event_ids = tuple(args.reconcile_outbox_event_id or ())
    if len(job_ids) + len(event_ids) > MAX_RELEASE_SET_SIZE:
        raise DrillError(f"reconciliation set must contain at most {MAX_RELEASE_SET_SIZE} records")
    if len(set(job_ids)) != len(job_ids) or len(set(event_ids)) != len(event_ids):
        raise DrillError("reconciliation set must not contain duplicate IDs")
    has_selection = bool(job_ids or event_ids)
    supplied = (
        args.reconcile_actor_person_id,
        args.reconcile_tenant_id,
        args.reconcile_reason,
    )
    if has_selection and not all(supplied):
        raise DrillError("selected reconciliation requires actor, tenant, and reason")
    if not has_selection and any(value is not None for value in supplied):
        raise DrillError(
            "reconciliation actor, tenant, and reason require an explicit selected set"
        )
    if has_selection and not args.acknowledge_reconciliation:
        raise DrillError("selected reconciliation requires --acknowledge-reconciliation")
    if not has_selection and args.acknowledge_reconciliation:
        raise DrillError("--acknowledge-reconciliation requires an explicit selected set")
    if args.reconcile_reason is not None:
        reason = args.reconcile_reason.strip()
        if not reason or len(reason) > 500 or any(ord(character) < 32 for character in reason):
            raise DrillError("reconciliation reason must be printable and 1-500 characters")


def _config_from_args(args: argparse.Namespace) -> DrillConfig:
    workspace_root = _workspace_root()
    if args.execute and not args.acknowledge_isolated_target:
        raise DrillError("--execute requires --acknowledge-isolated-target")
    if not args.execute and args.acknowledge_isolated_target:
        raise DrillError("--acknowledge-isolated-target is valid only with --execute")
    _validate_reconciliation_args(args)
    workspace_mode, workspace_release_id, expected_head = _workspace_release_contract(
        workspace_root
    )
    backup = _validate_backup(args.backup, workspace_root=workspace_root)
    (
        backup_metadata,
        backup_captured_at,
        backup_release_id,
        backup_sha256,
        backup_metadata_sha256,
    ) = _validate_backup_metadata(
        args.backup_metadata,
        backup=backup,
        environment=args.environment,
        workspace_root=workspace_root,
        expected_migration_head=expected_head,
    )
    postgres_image = _validate_postgres_image(args.postgres_image)
    application_image = _validate_application_image(args.application_image)
    if backup_release_id != workspace_release_id:
        raise DrillError("backup release does not match the selected workspace release")
    # Deliberately last: validating configuration never creates this path.
    evidence_dir = _validate_evidence_dir(
        args.evidence_dir,
        workspace_root=workspace_root,
    )
    return DrillConfig(
        environment=args.environment,
        backup=backup,
        backup_metadata=backup_metadata,
        backup_sha256=backup_sha256,
        backup_metadata_sha256=backup_metadata_sha256,
        backup_captured_at=backup_captured_at,
        backup_release_id=backup_release_id,
        evidence_dir=evidence_dir,
        workspace_mode=workspace_mode,
        workspace_release_id=workspace_release_id,
        expected_migration_head=expected_head,
        postgres_image=postgres_image,
        application_image=application_image,
        execute=args.execute,
        acknowledge_isolated_target=args.acknowledge_isolated_target,
        reconcile_job_ids=tuple(args.reconcile_job_id or ()),
        reconcile_outbox_event_ids=tuple(args.reconcile_outbox_event_id or ()),
        reconcile_actor_person_id=args.reconcile_actor_person_id,
        reconcile_tenant_id=args.reconcile_tenant_id,
        reconcile_reason=(args.reconcile_reason.strip() if args.reconcile_reason else None),
        acknowledge_reconciliation=args.acknowledge_reconciliation,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=("staging", "production"))
    parser.add_argument("--backup", required=True, help="absolute custom-format pg_dump path")
    parser.add_argument(
        "--backup-metadata",
        required=True,
        help="absolute JSON metadata paired with the logical dump",
    )
    parser.add_argument("--evidence-dir", required=True, help="absolute new directory path")
    parser.add_argument("--application-image", required=True, help="exact local sha256 image ID")
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--execute", action="store_true", help="run the disposable drill")
    parser.add_argument(
        "--acknowledge-isolated-target",
        action="store_true",
        help="acknowledge creation and exact-label cleanup of disposable resources",
    )
    parser.add_argument("--reconcile-job-id", action="append", type=UUID)
    parser.add_argument("--reconcile-outbox-event-id", action="append", type=UUID)
    parser.add_argument("--reconcile-actor-person-id", type=UUID)
    parser.add_argument("--reconcile-tenant-id", type=UUID)
    parser.add_argument("--reconcile-reason", type=str)
    parser.add_argument(
        "--acknowledge-reconciliation",
        action="store_true",
        help="acknowledge release of exactly the named held records",
    )
    return parser


def _dry_run_plan(config: DrillConfig) -> dict[str, Any]:
    has_selection = bool(config.reconcile_job_ids or config.reconcile_outbox_event_ids)
    return {
        "mode": "dry-run",
        "environment": config.environment,
        "backup_sha256": config.backup_sha256,
        "backup_metadata_sha256": config.backup_metadata_sha256,
        "backup_captured_at": config.backup_captured_at.isoformat(),
        "backup_release_id": config.backup_release_id,
        "workspace_mode": config.workspace_mode,
        "workspace_release_id": config.workspace_release_id,
        "expected_migration_head": config.expected_migration_head,
        "postgres_image": config.postgres_image,
        "application_image": config.application_image,
        "application_image_local_check": "deferred-until-execute-preflight",
        "target": (
            "new PostgreSQL 18 container as 999:999, new labeled volume, "
            "internal-only network, generated database identity, no published port"
        ),
        "writes": [],
        "external_connections": [],
        "reconciliation": "selected IDs only" if has_selection else "disabled",
    }


def _create_evidence_dir(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)
    except OSError as error:
        raise DrillError("evidence directory could not be created exclusively") from error
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise DrillError("evidence directory identity changed during creation")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o700:
        raise DrillError("evidence directory permissions are not 0700")


def _safe_remove_evidence_temp(temp: Path, evidence_dir: Path, created: bool) -> None:
    if not created or temp.parent != evidence_dir:
        return
    try:
        metadata = temp.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode) or temp.is_symlink():
        raise DrillError("refusing to remove a non-regular evidence temporary path")
    temp.unlink()


def _fsync_directory(path: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if directory_flag is None:
        return
    descriptor = os.open(path, os.O_RDONLY | directory_flag)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_evidence(evidence_dir: Path, evidence: Mapping[str, Any], run_id: str) -> Path:
    if TOKEN_PATTERN.fullmatch(run_id) is None:
        raise DrillError("evidence run identifier is invalid")
    target = evidence_dir / f"restore-drill-{run_id}.json"
    temp = evidence_dir / f".restore-drill-{run_id}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    created_temp = False
    try:
        descriptor = os.open(temp, flags | no_follow, 0o600)
        created_temp = True
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            stream.write(json.dumps(evidence, indent=2, sort_keys=True))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.link(temp, target)
        temp.unlink()
        created_temp = False
        mode = stat.S_IMODE(target.stat().st_mode)
        if os.name != "nt" and mode != 0o600:
            raise DrillError("evidence JSON permissions are not 0600")
        _fsync_directory(evidence_dir)
        return target
    except FileExistsError as error:
        raise DrillError("evidence JSON already exists; refusing to overwrite it") from error
    except DrillError:
        raise
    except OSError as error:
        raise DrillError("evidence JSON could not be published atomically") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _safe_remove_evidence_temp(temp, evidence_dir, created_temp)


def _raise_on_signal(signum: int, _frame: FrameType | None) -> None:
    try:
        signal_name = signal.Signals(signum).name
    except ValueError:
        signal_name = "signal"
    raise DrillInterrupted(f"interrupted by {signal_name}; cleanup was required")


def _install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _raise_on_signal)
    return previous


def _ignore_cleanup_signals() -> None:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, signal.SIG_IGN)


def _restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _execute(config: DrillConfig) -> tuple[dict[str, Any], Path]:
    run_id = _short_token()
    target = _target_for(run_id)
    # Exact-image attestation uses named, labeled, no-network containers with
    # forced cleanup and precedes persistent target/evidence mutation.
    _preflight(target, config)
    drill_started_at = _now()
    evidence: dict[str, Any] = {
        "result": "failed",
        "run_id": run_id,
        "environment": config.environment,
        "drill_started_at": drill_started_at.isoformat(),
        "backup_sha256": config.backup_sha256,
        "backup_metadata_sha256": config.backup_metadata_sha256,
        "backup_captured_at": config.backup_captured_at.isoformat(),
        "backup_release_id": config.backup_release_id,
        "workspace_mode": config.workspace_mode,
        "workspace_release_id": config.workspace_release_id,
        "postgres_image": config.postgres_image,
        "application_image": config.application_image,
        "target": {
            "container": target.container,
            "network": target.network,
            "volume": target.volume,
            "database": target.database,
            "role": target.role,
            "network_internal": True,
            "published_ports": [],
            "runtime_user": "999:999",
        },
        "external_connections": [],
        "cleanup": {
            "status": "pending",
            "label_key": LABEL_KEY,
            "label_value": run_id,
            "exact_resources": {
                "containers": [
                    target.container,
                    target.init_container,
                    target.probe_container,
                ],
                "network": target.network,
                "volume": target.volume,
            },
        },
        "operation_gate": {"status": "failed"},
    }
    previous_handlers = _install_signal_handlers()
    evidence_directory_ready = False
    operation_errors: list[str] = []
    rto_started: float | None = None
    rto_observed_seconds = 0.0
    rto_completed = False
    evidence_path: Path | None = None
    try:
        try:
            _create_evidence_dir(config.evidence_dir)
            evidence_directory_ready = True
            rto_started = time.perf_counter()
            _create_target(target, config)
            evidence["postgres_identity"] = _verify_target_identity(target)
            _restore_dump(target)
            evidence["schema"] = _schema_and_migration(
                target,
                config.expected_migration_head,
            )
            evidence["row_counts"] = _row_counts(target, config.expected_migration_head)
            contract = parity_contract_for_head(config.expected_migration_head)
            if contract is not None:
                _verify_versioned_backup_parity(config, evidence["row_counts"])
                evidence["parity_contract"] = contract
            evidence["invariants_before_hold"] = _invariants(target)
            before_hold = _side_effect_counts(target)
            evidence["counts_before_hold"] = before_hold.as_dict()
            probe_payload = _run_probe(
                target,
                config.application_image,
                (
                    "mark-and-prove",
                    "--reason",
                    "restore drill requires explicit selected reconciliation",
                ),
                "run sanctioned restore marker and worker hold proof",
            )
            marker, worker_proof = _validate_mark_probe(probe_payload)
            evidence["restore_marker"] = marker
            evidence["worker_hold_proof"] = worker_proof
            after_hold = _side_effect_counts(target)
            evidence["counts_after_hold"] = after_hold.as_dict()
            _assert_hold_transition(before_hold, after_hold, marker)
            rto_observed_seconds = time.perf_counter() - rto_started
            rto_completed = True

            if config.reconcile_job_ids or config.reconcile_outbox_event_ids:
                reconcile_payload = _run_probe(
                    target,
                    config.application_image,
                    _reconciliation_action_args(config),
                    "reconcile exact selected held records",
                    operations_tenant_id=config.reconcile_tenant_id,
                )
                reconciliation = _validate_reconcile_probe(
                    reconcile_payload,
                    config,
                    marker["generation"],
                )
                after_reconciliation = _side_effect_counts(target)
                _assert_reconciliation_transition(
                    after_hold,
                    after_reconciliation,
                    config,
                )
                evidence["reconciliation"] = reconciliation
                evidence["counts_after_reconciliation"] = after_reconciliation.as_dict()
            else:
                evidence["reconciliation"] = {
                    "requested": False,
                    "released_job_ids": [],
                    "released_outbox_event_ids": [],
                    "recovery_state_remains_held": True,
                }
                evidence["counts_after_reconciliation"] = after_hold.as_dict()
            evidence["operation_gate"] = {"status": "passed"}
        except DrillError as error:
            operation_errors.append(str(error))
        except KeyboardInterrupt:
            operation_errors.append("interrupted by operator; cleanup was required")
        except Exception as error:  # pragma: no cover - live dependency failure
            operation_errors.append(f"unexpected {type(error).__name__} failure")
        finally:
            if rto_started is not None and not rto_completed:
                rto_observed_seconds = time.perf_counter() - rto_started
            _ignore_cleanup_signals()
            try:
                target.cleanup()
                cleanup = evidence["cleanup"]
                if isinstance(cleanup, dict):
                    cleanup["status"] = "completed"
            except DrillError as error:
                operation_errors.append(str(error))
                cleanup = evidence["cleanup"]
                if isinstance(cleanup, dict):
                    cleanup["status"] = "failed-operator-attention-required"

            rpo_seconds = max(
                0.0,
                (drill_started_at - config.backup_captured_at).total_seconds(),
            )
            rpo_status = "passed" if rpo_seconds <= RPO_TARGET_SECONDS else "failed"
            rto_status = (
                "passed"
                if rto_completed and rto_observed_seconds <= RTO_TARGET_SECONDS
                else "failed"
            )
            objective_status = (
                "passed" if rpo_status == "passed" and rto_status == "passed" else "failed"
            )
            evidence["rpo_gate"] = {
                "status": rpo_status,
                "target_seconds": RPO_TARGET_SECONDS,
                "observed_backup_age_seconds": round(rpo_seconds, 3),
            }
            evidence["rto_gate"] = {
                "status": rto_status,
                "target_seconds": RTO_TARGET_SECONDS,
                "observed_seconds": round(rto_observed_seconds, 3),
                "completion_boundary": "restore-verified-marker-held-worker-provider-call-blocked",
            }
            evidence["objective_gate"] = {"status": objective_status}
            if operation_errors:
                evidence["operation_gate"] = {
                    "status": "failed",
                    "errors": operation_errors,
                }
                evidence["result"] = "failed"
            elif objective_status == "failed":
                evidence["result"] = "objective-failed"
            else:
                evidence["result"] = "passed"
            evidence["drill_completed_at"] = _now().isoformat()
            if evidence_directory_ready:
                evidence_path = _write_evidence(config.evidence_dir, evidence, run_id)
    finally:
        _restore_signal_handlers(previous_handlers)

    if not evidence_directory_ready:
        message = operation_errors[0] if operation_errors else "evidence directory was not created"
        raise DrillError(message)
    if evidence_path is None:
        raise DrillError("restore-drill evidence was not created")
    return evidence, evidence_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        config = _config_from_args(parser.parse_args(argv))
        if not config.execute:
            print(json.dumps(_dry_run_plan(config), indent=2, sort_keys=True))
            return 0
        outer_handlers = _install_signal_handlers()
        try:
            with _stable_restore_inputs(config) as stable_config:
                evidence, evidence_path = _execute(stable_config)
        finally:
            _restore_signal_handlers(outer_handlers)
        result = str(evidence["result"])
        print(
            json.dumps(
                {
                    "result": result,
                    "evidence": str(evidence_path),
                    "operation_gate": evidence["operation_gate"],
                    "objective_gate": evidence["objective_gate"],
                },
                sort_keys=True,
            )
        )
        if result == "passed":
            return 0
        if result == "objective-failed":
            return 3
        return 2
    except (DrillError, OSError, ValueError) as error:
        print(f"restore drill failed closed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

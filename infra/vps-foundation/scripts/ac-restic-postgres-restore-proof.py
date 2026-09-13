#!/usr/bin/env python3
"""Prove an off-site logical PostgreSQL backup without touching a live target.

This program is intentionally stdlib-only.  It reads Restic metadata, restores
only the two files produced by the logical backup writer into a short-lived,
root-owned directory, and delegates database/schema/invariant/recovery-hold
proof to the immutable application's existing ``restore-drill.py``.

The caller is expected to be the root-owned Infisical/Restic wrapper.  No
credential, Restic output, child stderr, or database payload is printed.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ENVIRONMENTS = ("staging", "production")
RESTIC_TAG = "authority-closers-postgres-logical"
RESTORE_ROOT = Path("/srv/authority-closers/recovery-tmp/postgres-logical")
EVIDENCE_ROOT = Path("/srv/authority-closers/recovery-evidence/postgres-logical")
APPLICATION_ROOT = Path("/srv/authority-closers/application")
MAX_SNAPSHOT_AGE_SECONDS = 15 * 60
MAX_CLOCK_SKEW_SECONDS = 60
MAX_RESTIC_CAPTURE_LAG_SECONDS = 5 * 60
MAX_DUMP_BYTES = 8 * 1024 * 1024
MAX_CLEANUP_ENTRIES = 128
MAX_CLEANUP_SECONDS = 30
SNAPSHOT_TIMEOUT_SECONDS = 120
RESTORE_TIMEOUT_SECONDS = 15 * 60
DRILL_TIMEOUT_SECONDS = 70 * 60
RELEASE_ID_RE = re.compile(r"^[0-9a-f]{40}$")
SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAPTURE_DIR_RE = re.compile(r"^[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9]+-(staging|production)$")
TEMP_DIR_RE = re.compile(r"^\.logical-[0-9a-f]{24}$")
EVIDENCE_FILE_RE = re.compile(r"^restore-drill-[0-9a-f]{12}\.json$")
RELEASE_IMAGE_KEYS = {
    "AC_ADMIN_IMAGE",
    "AC_ADMIN_REGISTRY_DIGEST",
    "AC_ADMIN_TRANSPORT_DIGEST",
    "AC_API_IMAGE",
    "AC_API_REGISTRY_DIGEST",
    "AC_API_TRANSPORT_DIGEST",
    "AC_LEARNER_IMAGE",
    "AC_LEARNER_REGISTRY_DIGEST",
    "AC_LEARNER_TRANSPORT_DIGEST",
    "AC_MIGRATION_HEAD",
    "AC_RELEASE_ID",
}
COACH_RELEASE_IMAGE_KEYS = RELEASE_IMAGE_KEYS | {
    "AC_COACH_IMAGE",
    "AC_COACH_REGISTRY_DIGEST",
    "AC_COACH_TRANSPORT_DIGEST",
}
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
CAPABILITY_PARITY_TABLES = PARITY_TABLES + ("capability_grants", "capability_revocations")


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
# 20260909_0023 extends the immutable authoring-command operation catalogue,
# and 20260909_0024/0025 add the reviewed Studio library index and course
# creation operation without changing the restored table inventory or parity
# contract. Each exact head remains an explicit reviewed compatibility row.
REVISION_PARITY_MIGRATION_HEAD = "20260909_0023"
REVISION_PARITY_CONTRACT = AUTHORING_PARITY_CONTRACT
REVISION_PARITY_TABLES = AUTHORING_PARITY_TABLES
MEDIA_LIBRARY_PARITY_MIGRATION_HEAD = "20260909_0024"
MEDIA_LIBRARY_PARITY_CONTRACT = REVISION_PARITY_CONTRACT
MEDIA_LIBRARY_PARITY_TABLES = REVISION_PARITY_TABLES
COURSE_CREATION_PARITY_MIGRATION_HEAD = "20260909_0025"
COURSE_CREATION_PARITY_CONTRACT = MEDIA_LIBRARY_PARITY_CONTRACT
COURSE_CREATION_PARITY_TABLES = MEDIA_LIBRARY_PARITY_TABLES
# These heads add canonical rows. They must not reuse the older 53-table
# contract or silently omit upload admission/public identity from restore proof.
STUDIO_VIDEO_PARITY_MIGRATION_HEAD = "20260910_0026"
STUDIO_VIDEO_PARITY_CONTRACT = "ac-postgres-parity-v6"
STUDIO_VIDEO_PARITY_TABLES = COURSE_CREATION_PARITY_TABLES + ("studio_video_uploads",)
COMMUNITY_PARITY_MIGRATION_HEAD = "20260910_0027"
COMMUNITY_PARITY_CONTRACT = "ac-postgres-parity-v7"
COMMUNITY_PARITY_TABLES = STUDIO_VIDEO_PARITY_TABLES + ("academy_public_profiles",)
GLOBAL_COMMUNITY_PARITY_MIGRATION_HEAD = "20260910_0028"
GLOBAL_COMMUNITY_PARITY_CONTRACT = "ac-postgres-parity-v8"
GLOBAL_COMMUNITY_PARITY_TABLES = COMMUNITY_PARITY_TABLES + (
    "community_public_profiles",
    "academy_leaderboard_preferences",
)
APP_UPDATES_PARITY_MIGRATION_HEAD = "20260910_0029"
APP_UPDATES_PARITY_CONTRACT = "ac-postgres-parity-v9"
APP_UPDATES_PARITY_TABLES = GLOBAL_COMMUNITY_PARITY_TABLES + ("app_update_read_receipts",)
SALES_XRAY_PARITY_MIGRATION_HEAD = "20260913_0030"
SALES_XRAY_PARITY_CONTRACT = "ac-postgres-parity-v10"
SALES_XRAY_PARITY_NEW_TABLES = (
    "conversation_budget_accounts",
    "conversation_review_cursors",
    "conversation_minute_accounts",
    "conversation_permissions",
    "conversation_recordings",
    "conversation_checkpoints",
    "conversation_commands",
    "conversation_quotes",
    "conversation_runs",
    "conversation_reviews",
    "conversation_quote_acceptances",
    "conversation_provider_configurations",
    "conversation_report_drafts",
)
SALES_XRAY_PARITY_TABLES = APP_UPDATES_PARITY_TABLES + SALES_XRAY_PARITY_NEW_TABLES
INFERENCE_PARITY_MIGRATION_HEAD = "20260913_0031"
INFERENCE_PARITY_CONTRACT = "ac-postgres-parity-v11"
INFERENCE_PARITY_NEW_TABLES = ("conversation_inference_tasks",)
INFERENCE_PARITY_TABLES = SALES_XRAY_PARITY_TABLES + INFERENCE_PARITY_NEW_TABLES
PLANS_PARITY_MIGRATION_HEAD = "20260913_0032"
PLANS_PARITY_CONTRACT = "ac-postgres-parity-v12"
PLANS_PARITY_NEW_TABLES = (
    "conversation_processing_plans",
    "conversation_plan_stage_authorizations",
)
PLANS_PARITY_TABLES = INFERENCE_PARITY_TABLES + PLANS_PARITY_NEW_TABLES
COMMUNITY_CONNECTIONS_PARITY_MIGRATION_HEAD = "20260913_0033"
COMMUNITY_CONNECTIONS_PARITY_CONTRACT = "ac-postgres-parity-v13"
COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES = (
    "community_discovery_preferences",
    "community_connections",
    "community_connection_events",
    "community_blocks",
    "community_reports",
)
COMMUNITY_CONNECTIONS_PARITY_TABLES = PLANS_PARITY_TABLES + COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES
REVIEWS_PARITY_MIGRATION_HEAD = "20260913_0034"
REVIEWS_PARITY_CONTRACT = "ac-postgres-parity-v14"
REVIEWS_PARITY_NEW_TABLES = (
    "conversation_review_assignments",
    "conversation_review_revocations",
    "conversation_review_feedback",
)
REVIEWS_PARITY_TABLES = COMMUNITY_CONNECTIONS_PARITY_TABLES + REVIEWS_PARITY_NEW_TABLES
REVIEW_INVITATIONS_PARITY_MIGRATION_HEAD = "20260913_0035"
REVIEW_INVITATIONS_PARITY_CONTRACT = "ac-postgres-parity-v15"
REVIEW_INVITATIONS_PARITY_NEW_TABLES = (
    "conversation_review_invitations",
    "conversation_review_invitation_revocations",
    "conversation_review_invitation_acceptances",
)
REVIEW_INVITATIONS_PARITY_TABLES = REVIEWS_PARITY_TABLES + REVIEW_INVITATIONS_PARITY_NEW_TABLES
ACQUISITION_PARITY_MIGRATION_HEAD = "20260914_0036"
ACQUISITION_PARITY_CONTRACT = "ac-postgres-parity-v16"
ACQUISITION_PARITY_NEW_TABLES = (
    "conversation_visitors",
    "conversation_visitor_claims",
    "conversation_acquisition_usage",
    "conversation_acquisition_settlements",
)
ACQUISITION_PARITY_TABLES = REVIEW_INVITATIONS_PARITY_TABLES + ACQUISITION_PARITY_NEW_TABLES
PROCESSING_OWNERSHIP_PARITY_MIGRATION_HEAD = "20260914_0037"
PROCESSING_OWNERSHIP_PARITY_CONTRACT = "ac-postgres-parity-v17"
PROCESSING_OWNERSHIP_PARITY_NEW_TABLES = (
    "conversation_processing_principals",
    "conversation_processing_leases",
    "conversation_guest_submissions",
)
PROCESSING_OWNERSHIP_PARITY_TABLES = (
    ACQUISITION_PARITY_TABLES + PROCESSING_OWNERSHIP_PARITY_NEW_TABLES
)
VERSIONED_PARITY_CONTRACTS = {
    CAPABILITY_PARITY_MIGRATION_HEAD: (CAPABILITY_PARITY_CONTRACT, CAPABILITY_PARITY_TABLES),
    PRACTICE_PARITY_MIGRATION_HEAD: (PRACTICE_PARITY_CONTRACT, PRACTICE_PARITY_TABLES),
    FOCUS_PARITY_MIGRATION_HEAD: (FOCUS_PARITY_CONTRACT, FOCUS_PARITY_TABLES),
    AUTHORING_PARITY_MIGRATION_HEAD: (AUTHORING_PARITY_CONTRACT, AUTHORING_PARITY_TABLES),
    REVISION_PARITY_MIGRATION_HEAD: (REVISION_PARITY_CONTRACT, REVISION_PARITY_TABLES),
    MEDIA_LIBRARY_PARITY_MIGRATION_HEAD: (
        MEDIA_LIBRARY_PARITY_CONTRACT,
        MEDIA_LIBRARY_PARITY_TABLES,
    ),
    COURSE_CREATION_PARITY_MIGRATION_HEAD: (
        COURSE_CREATION_PARITY_CONTRACT,
        COURSE_CREATION_PARITY_TABLES,
    ),
    STUDIO_VIDEO_PARITY_MIGRATION_HEAD: (
        STUDIO_VIDEO_PARITY_CONTRACT,
        STUDIO_VIDEO_PARITY_TABLES,
    ),
    COMMUNITY_PARITY_MIGRATION_HEAD: (
        COMMUNITY_PARITY_CONTRACT,
        COMMUNITY_PARITY_TABLES,
    ),
    GLOBAL_COMMUNITY_PARITY_MIGRATION_HEAD: (
        GLOBAL_COMMUNITY_PARITY_CONTRACT,
        GLOBAL_COMMUNITY_PARITY_TABLES,
    ),
    APP_UPDATES_PARITY_MIGRATION_HEAD: (
        APP_UPDATES_PARITY_CONTRACT,
        APP_UPDATES_PARITY_TABLES,
    ),
    SALES_XRAY_PARITY_MIGRATION_HEAD: (
        SALES_XRAY_PARITY_CONTRACT,
        SALES_XRAY_PARITY_TABLES,
    ),
    INFERENCE_PARITY_MIGRATION_HEAD: (
        INFERENCE_PARITY_CONTRACT,
        INFERENCE_PARITY_TABLES,
    ),
    PLANS_PARITY_MIGRATION_HEAD: (PLANS_PARITY_CONTRACT, PLANS_PARITY_TABLES),
    COMMUNITY_CONNECTIONS_PARITY_MIGRATION_HEAD: (
        COMMUNITY_CONNECTIONS_PARITY_CONTRACT,
        COMMUNITY_CONNECTIONS_PARITY_TABLES,
    ),
    REVIEWS_PARITY_MIGRATION_HEAD: (REVIEWS_PARITY_CONTRACT, REVIEWS_PARITY_TABLES),
    REVIEW_INVITATIONS_PARITY_MIGRATION_HEAD: (
        REVIEW_INVITATIONS_PARITY_CONTRACT,
        REVIEW_INVITATIONS_PARITY_TABLES,
    ),
    ACQUISITION_PARITY_MIGRATION_HEAD: (
        ACQUISITION_PARITY_CONTRACT,
        ACQUISITION_PARITY_TABLES,
    ),
    PROCESSING_OWNERSHIP_PARITY_MIGRATION_HEAD: (
        PROCESSING_OWNERSHIP_PARITY_CONTRACT,
        PROCESSING_OWNERSHIP_PARITY_TABLES,
    ),
}


def parity_tables_for_head(migration_head: str) -> tuple[str, ...]:
    if migration_head in LEGACY_PARITY_MIGRATION_HEADS:
        return PARITY_TABLES
    if migration_head in VERSIONED_PARITY_CONTRACTS:
        return VERSIONED_PARITY_CONTRACTS[migration_head][1]
    raise RestoreProofError("migration head has no reviewed row-count parity contract")


def parity_contract_for_head(migration_head: str) -> str | None:
    parity_tables_for_head(migration_head)
    if migration_head in LEGACY_PARITY_MIGRATION_HEADS:
        return None
    return VERSIONED_PARITY_CONTRACTS[migration_head][0]


class RestoreProofError(RuntimeError):
    """A bounded operator-facing failure that never contains secret output."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class SnapshotPair:
    capture_dir: str
    dump_path: str
    metadata_path: str


@dataclass(frozen=True, slots=True)
class ApplicationRelease:
    environment: str
    release_dir: Path
    restore_drill: Path
    api_image: str
    migration_head: str


def _parse_timestamp(value: object, *, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise RestoreProofError(f"{label} timestamp is invalid")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as error:
        raise RestoreProofError(f"{label} timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise RestoreProofError(f"{label} timestamp has no timezone")
    return parsed.astimezone(dt.UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RestoreProofError("restored logical backup could not be hashed") from error
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    step: str,
    *,
    timeout_seconds: int,
    capture_stdout: bool = False,
) -> str:
    try:
        process = subprocess.Popen(  # noqa: S603 - command uses fixed tools and validated paths/IDs
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=(os.name == "posix"),
            env=os.environ.copy(),
        )
        try:
            stdout, _stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            if os.name == "posix":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.communicate()
            raise RestoreProofError(f"{step} timed out") from error
    except RestoreProofError:
        raise
    except OSError as error:
        raise RestoreProofError(f"{step} could not start") from error
    if process.returncode != 0:
        raise RestoreProofError(f"{step} failed")
    return stdout if capture_stdout and stdout is not None else ""


def _validate_restic_record(record: object, environment: str) -> Snapshot:
    if not isinstance(record, Mapping):
        raise RestoreProofError("Restic snapshot listing has an invalid record")
    snapshot_id = record.get("id")
    if not isinstance(snapshot_id, str) or SNAPSHOT_ID_RE.fullmatch(snapshot_id) is None:
        raise RestoreProofError("Restic snapshot listing has an invalid snapshot identity")
    tags = record.get("tags")
    required_tags = {RESTIC_TAG, f"environment={environment}"}
    if (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
        or any(tags.count(tag) != 1 for tag in required_tags)
        or not required_tags.issubset(tags)
    ):
        raise RestoreProofError("Restic snapshot tags are ambiguous")
    created_at = _parse_timestamp(record.get("time"), label="Restic snapshot")
    return Snapshot(snapshot_id=snapshot_id, created_at=created_at)


def select_latest_snapshot(
    raw_json: str,
    environment: str,
    *,
    now: dt.datetime | None = None,
) -> Snapshot:
    """Select one, and only one, newest matching snapshot from a full listing."""

    try:
        records = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise RestoreProofError("Restic snapshot listing is not valid JSON") from error
    if not isinstance(records, list) or not records:
        raise RestoreProofError("No matching logical PostgreSQL snapshot exists")
    snapshots = [_validate_restic_record(record, environment) for record in records]
    latest_time = max(snapshot.created_at for snapshot in snapshots)
    latest = [snapshot for snapshot in snapshots if snapshot.created_at == latest_time]
    if len(latest) != 1:
        raise RestoreProofError("Latest logical PostgreSQL snapshot is ambiguous")
    current = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    age = (current - latest[0].created_at).total_seconds()
    if age < -MAX_CLOCK_SKEW_SECONDS or age > MAX_SNAPSHOT_AGE_SECONDS:
        raise RestoreProofError("Latest logical PostgreSQL snapshot is stale")
    return latest[0]


def validate_snapshot_capture_timing(
    snapshot: Snapshot,
    captured_at: dt.datetime,
    *,
    now: dt.datetime | None = None,
) -> None:
    """Bind the Restic timestamp to a fresh database capture timestamp."""

    current = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    capture_age = (current - captured_at).total_seconds()
    snapshot_capture_delta = (snapshot.created_at - captured_at).total_seconds()
    if (
        capture_age < -MAX_CLOCK_SKEW_SECONDS
        or capture_age > MAX_SNAPSHOT_AGE_SECONDS
        or snapshot_capture_delta < -MAX_CLOCK_SKEW_SECONDS
        or snapshot_capture_delta > MAX_RESTIC_CAPTURE_LAG_SECONDS + MAX_CLOCK_SKEW_SECONDS
    ):
        raise RestoreProofError("logical backup capture timing is stale or inconsistent")


def _normal_snapshot_path(raw_path: object) -> str:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise RestoreProofError("Restic snapshot contains an unsafe path")
    path = PurePosixPath(raw_path)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RestoreProofError("Restic snapshot contains an unsafe path")
    return "/".join(parts)


def _pair_candidate(path: str, environment: str) -> tuple[str, str] | None:
    prefix = f"srv/authority-closers/backups/application/{environment}/logical/"
    if not path.startswith(prefix):
        return None
    remainder = path[len(prefix) :]
    capture_dir, separator, filename = remainder.partition("/")
    if not separator or CAPTURE_DIR_RE.fullmatch(capture_dir) is None:
        return None
    if filename not in {"backup.dump", "metadata.json"} or "/" in filename:
        return None
    return capture_dir, filename


def select_snapshot_pair(
    raw_json_lines: str, environment: str, expected_snapshot_id: str
) -> SnapshotPair:
    """Require a snapshot tree with exactly one atomic logical pair."""

    if SHA256_RE.fullmatch(expected_snapshot_id) is None:
        raise RestoreProofError("Restic snapshot tree binding is invalid")
    entries: list[tuple[str, str]] = []
    directories: set[str] = set()
    seen_paths: set[str] = set()
    snapshot_headers = 0
    lines = [line for line in raw_json_lines.splitlines() if line.strip()]
    if not lines:
        raise RestoreProofError("Restic snapshot tree is empty")
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise RestoreProofError("Restic snapshot tree is not valid JSON") from error
        if not isinstance(record, Mapping):
            raise RestoreProofError("Restic snapshot tree has an invalid node")
        struct_type = record.get("struct_type")
        if struct_type == "snapshot":
            snapshot_headers += 1
            if snapshot_headers != 1 or record.get("id") != expected_snapshot_id:
                raise RestoreProofError("Restic snapshot tree binding is inconsistent")
            continue
        if struct_type != "node":
            raise RestoreProofError("Restic snapshot tree has an invalid message type")
        node_type = record.get("type")
        if node_type == "dir":
            raw_path = record.get("path")
            if raw_path == "/":
                continue
            path = _normal_snapshot_path(raw_path)
            directories.add(path)
            continue
        if node_type != "file":
            raise RestoreProofError("Restic snapshot contains a non-regular entry")
        path = _normal_snapshot_path(record.get("path"))
        if path in seen_paths:
            raise RestoreProofError("Restic snapshot contains an ambiguous duplicate path")
        seen_paths.add(path)
        candidate = _pair_candidate(path, environment)
        if candidate is None:
            raise RestoreProofError("Restic snapshot contains an unexpected file path")
        entries.append(candidate)
    if snapshot_headers != 1:
        raise RestoreProofError("Restic snapshot tree lacks an exact snapshot header")
    captures = {capture for capture, _filename in entries}
    if len(captures) > 1:
        raise RestoreProofError("Restic snapshot contains logical files from multiple captures")
    if len(entries) != 2 or {filename for _capture, filename in entries} != {
        "backup.dump",
        "metadata.json",
    }:
        raise RestoreProofError("Restic snapshot does not contain exactly one logical pair")
    if len(captures) != 1:
        raise RestoreProofError("Restic snapshot does not contain one capture directory")
    capture_dir = captures.pop()
    prefix = f"srv/authority-closers/backups/application/{environment}/logical/{capture_dir}/"
    allowed_directories = {
        "srv",
        "srv/authority-closers",
        "srv/authority-closers/backups",
        "srv/authority-closers/backups/application",
        f"srv/authority-closers/backups/application/{environment}",
        f"srv/authority-closers/backups/application/{environment}/logical",
        prefix.rstrip("/"),
    }
    if not directories.issubset(allowed_directories):
        raise RestoreProofError("Restic snapshot contains an unexpected directory path")
    return SnapshotPair(
        capture_dir=capture_dir,
        dump_path=prefix + "backup.dump",
        metadata_path=prefix + "metadata.json",
    )


def _owner_is_root(path: Path) -> bool:
    try:
        return path.lstat().st_uid == 0
    except OSError as error:
        raise RestoreProofError("recovery path ownership could not be verified") from error


def _require_directory(path: Path, *, label: str, mode: int | None = None) -> Path:
    if path.is_symlink():
        raise RestoreProofError(f"{label} must not be a symbolic link")
    if os.name == "posix" and not hasattr(os, "O_NOFOLLOW"):
        raise RestoreProofError("the Linux no-follow filesystem primitive is unavailable")
    for ancestor in path.parents:
        if ancestor.exists() and ancestor.is_symlink():
            raise RestoreProofError(f"{label} has a symbolic-link ancestor")
    try:
        path.mkdir(mode=mode or 0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
    except OSError as error:
        raise RestoreProofError(f"{label} could not be prepared") from error
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink() or not _owner_is_root(path):
        raise RestoreProofError(f"{label} is not a root-owned directory")
    if mode is not None:
        try:
            path.chmod(mode)
        except OSError as error:
            raise RestoreProofError(f"{label} permissions could not be fixed") from error
    return path


def create_restore_directory(root: Path = RESTORE_ROOT) -> Path:
    _require_directory(root, label="bounded restore root", mode=0o700)
    for _attempt in range(8):
        candidate = root / f".logical-{secrets.token_hex(12)}"
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        except OSError as error:
            raise RestoreProofError("bounded restore directory could not be created") from error
        if (
            candidate.parent != root
            or TEMP_DIR_RE.fullmatch(candidate.name) is None
            or candidate.is_symlink()
            or not _owner_is_root(candidate)
        ):
            raise RestoreProofError("bounded restore directory identity is unsafe")
        return candidate
    raise RestoreProofError("bounded restore directory identity is ambiguous")


def _safe_tree_entries(root: Path) -> Iterable[Path]:
    try:
        for current, directories, files in os.walk(root, topdown=False, followlinks=False):
            current_path = Path(current)
            for name in (*files, *directories):
                yield current_path / name
    except OSError as error:
        raise RestoreProofError("restored logical tree could not be inspected") from error


def remove_restore_directory(path: Path, root: Path = RESTORE_ROOT) -> None:
    """Remove one exact temporary tree, refusing symlinks and dirty ownership."""

    if path.parent != root or TEMP_DIR_RE.fullmatch(path.name) is None or path.is_symlink():
        raise RestoreProofError("refusing to remove an unbounded restore directory")
    if not path.exists() or not path.is_dir() or not _owner_is_root(path):
        raise RestoreProofError("bounded restore directory is missing or unsafe")
    cleanup_started = time.monotonic()
    for inspected_entries, entry in enumerate(_safe_tree_entries(path), start=1):
        if (
            inspected_entries > MAX_CLEANUP_ENTRIES
            or time.monotonic() - cleanup_started > MAX_CLEANUP_SECONDS
        ):
            raise RestoreProofError("bounded restore cleanup exceeded its fixed limit")
        try:
            metadata = entry.lstat()
        except OSError as error:
            raise RestoreProofError("bounded restore cleanup could not inspect an entry") from error
        if entry.is_symlink() or not _owner_is_root(entry):
            raise RestoreProofError("bounded restore cleanup found an unsafe entry")
        if stat.S_ISREG(metadata.st_mode):
            try:
                entry.unlink()
            except OSError as error:
                raise RestoreProofError(
                    "bounded restore cleanup could not remove a file"
                ) from error
        elif stat.S_ISDIR(metadata.st_mode):
            try:
                entry.rmdir()
            except OSError as error:
                raise RestoreProofError(
                    "bounded restore cleanup found a dirty directory"
                ) from error
        else:
            raise RestoreProofError("bounded restore cleanup found a non-regular entry")
    try:
        path.rmdir()
    except OSError as error:
        raise RestoreProofError("bounded restore cleanup was incomplete") from error


def _verify_restored_pair(root: Path, pair: SnapshotPair) -> tuple[Path, Path]:
    if not root.is_dir() or root.is_symlink() or not _owner_is_root(root):
        raise RestoreProofError("Restic restore root is not a root-owned directory")
    files: list[Path] = []
    for entry in _safe_tree_entries(root):
        try:
            metadata = entry.lstat()
        except OSError as error:
            raise RestoreProofError("restored logical tree could not be inspected") from error
        if entry.is_symlink() or not _owner_is_root(entry):
            raise RestoreProofError("restored logical tree contains an unsafe entry")
        if stat.S_ISREG(metadata.st_mode):
            files.append(entry)
        elif not stat.S_ISDIR(metadata.st_mode):
            raise RestoreProofError("restored logical tree contains a non-regular entry")
    expected_dump = root.joinpath(*PurePosixPath(pair.dump_path).parts)
    expected_metadata = root.joinpath(*PurePosixPath(pair.metadata_path).parts)
    if set(files) != {expected_dump, expected_metadata}:
        raise RestoreProofError("Restic restore did not produce exactly the logical pair")
    return expected_dump, expected_metadata


def _read_stable_source(path: Path, *, max_bytes: int) -> bytes:
    if os.name == "posix" and not hasattr(os, "O_NOFOLLOW"):
        raise RestoreProofError("the Linux no-follow filesystem primitive is unavailable")
    if path.is_symlink():
        raise RestoreProofError("validated logical backup changed to a symbolic link")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_size > max_bytes:
            raise RestoreProofError("validated logical backup source is unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RestoreProofError("validated logical backup source was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    except RestoreProofError:
        raise
    except OSError as error:
        raise RestoreProofError("validated logical backup source could not be copied") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise RestoreProofError("validated logical backup source changed during copy")
    return b"".join(chunks)


def _write_private_file(path: Path, data: bytes) -> None:
    if os.name == "posix" and not hasattr(os, "O_NOFOLLOW"):
        raise RestoreProofError("the Linux no-follow filesystem primitive is unavailable")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(data):
            written += os.write(descriptor, data[written:])
        os.fsync(descriptor)
    except OSError as error:
        raise RestoreProofError("stable logical backup staging could not be written") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if path.is_symlink() or not path.is_file() or not _owner_is_root(path):
        raise RestoreProofError("stable logical backup staging is unsafe")


def copy_stable_pair(dump_path: Path, metadata_path: Path, root: Path) -> tuple[Path, Path, Path]:
    """Copy the validated pair into a no-follow private path before Docker mounts it."""

    stable_dir = create_restore_directory(root)
    try:
        dump_data = _read_stable_source(dump_path, max_bytes=MAX_DUMP_BYTES)
        metadata_data = _read_stable_source(metadata_path, max_bytes=64 * 1024)
        _write_private_file(stable_dir / "backup.dump", dump_data)
        # The application restore drill requires the metadata sidecar to be
        # the dump's exact `.with_suffix(".json")` pair.
        _write_private_file(stable_dir / "backup.json", metadata_data)
        stable_dump = stable_dir / "backup.dump"
        stable_metadata = stable_dir / "backup.json"
        if _sha256(stable_dump) != hashlib.sha256(dump_data).hexdigest():
            raise RestoreProofError("stable logical backup dump digest changed during staging")
        if _sha256(stable_metadata) != hashlib.sha256(metadata_data).hexdigest():
            raise RestoreProofError("stable logical backup metadata digest changed during staging")
        if set(stable_dir.iterdir()) != {stable_dump, stable_metadata}:
            raise RestoreProofError("stable logical backup staging contains an unexpected entry")
        return stable_dir, stable_dump, stable_metadata
    except Exception:
        try:
            remove_restore_directory(stable_dir, root)
        except RestoreProofError as cleanup_error:
            raise RestoreProofError(
                "stable logical backup staging cleanup failed"
            ) from cleanup_error
        raise


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_proof_record(
    evidence_dir: Path,
    snapshot: Snapshot,
    pair: SnapshotPair,
    dump_path: Path,
    metadata_path: Path,
    release: ApplicationRelease,
    drill_evidence: Path,
) -> Path:
    """Publish the remote snapshot identity beside the drill's evidence."""

    target = evidence_dir / "off-site-restore-proof.json"
    if target.exists() or target.is_symlink():
        raise RestoreProofError("off-site restore proof evidence already exists")
    temporary = evidence_dir / ".off-site-restore-proof.tmp"
    payload = {
        "schema": "authority-closers.off-site-postgres-restore-proof.v1",
        "environment": release.environment,
        "restic_snapshot_id": snapshot.snapshot_id,
        "restic_snapshot_created_at": snapshot.created_at.isoformat(),
        "restic_tags": [RESTIC_TAG, f"environment={release.environment}"],
        "snapshot_pair": {
            "capture_directory": pair.capture_dir,
            "dump_path": pair.dump_path,
            "metadata_path": pair.metadata_path,
        },
        "restored_pair": {
            "dump_sha256": _sha256(dump_path),
            "metadata_sha256": _sha256(metadata_path),
        },
        "application_release_id": release.release_dir.name,
        "restore_drill_evidence": drill_evidence.name,
        "result": "passed",
    }
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        written = 0
        while written < len(encoded):
            written += os.write(descriptor, encoded[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, target)
        temporary.unlink()
        _fsync_directory(evidence_dir)
    except OSError as error:
        raise RestoreProofError("off-site restore proof evidence could not be published") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            if temporary.is_symlink():
                raise RestoreProofError("off-site restore proof temporary path is unsafe")
            try:
                temporary.unlink()
            except OSError as error:
                raise RestoreProofError(
                    "off-site restore proof temporary cleanup failed"
                ) from error
    if target.is_symlink() or not target.is_file() or not _owner_is_root(target):
        raise RestoreProofError("off-site restore proof evidence is unsafe")
    return target


def _validate_metadata(
    metadata_path: Path,
    dump_path: Path,
    environment: str,
    *,
    expected_migration_head: str,
    now: dt.datetime | None = None,
) -> tuple[str, dt.datetime, dict[str, int]]:
    try:
        metadata_stat = metadata_path.lstat()
        if (
            metadata_path.is_symlink()
            or not stat.S_ISREG(metadata_stat.st_mode)
            or metadata_stat.st_size > 64 * 1024
            or not _owner_is_root(metadata_path)
        ):
            raise RestoreProofError("logical backup metadata is unsafe")
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except RestoreProofError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreProofError("logical backup metadata is not valid UTF-8 JSON") from error
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
        "row_counts",
    }
    versioned_keys = expected_keys | {"parity_contract", "migration_head"}
    if not isinstance(payload, dict) or set(payload) not in (expected_keys, versioned_keys):
        raise RestoreProofError("logical backup metadata has an unexpected contract")
    tables = parity_tables_for_head(expected_migration_head)
    contract = parity_contract_for_head(expected_migration_head)
    if contract is not None:
        if (
            set(payload) != versioned_keys
            or payload.get("parity_contract") != contract
            or payload.get("migration_head") != expected_migration_head
        ):
            raise RestoreProofError("versioned backup requires exact migration and parity identity")
    elif set(payload) != expected_keys:
        raise RestoreProofError("legacy backup must retain its legacy parity contract")
    release_id = payload.get("release_id")
    if (
        payload.get("artifact_type") != "authority-closers-postgresql-logical"
        or payload.get("restic_tag") != RESTIC_TAG
        or payload.get("environment") != environment
        or payload.get("compose_project") != f"ac-application-{environment}"
        or payload.get("database_role") != "ac_backup"
        or payload.get("format") != "custom"
        or payload.get("verification") != "pg_restore --list"
        or payload.get("capture_clock") != "CLOCK_REALTIME"
        or not isinstance(release_id, str)
        or RELEASE_ID_RE.fullmatch(release_id) is None
    ):
        raise RestoreProofError("logical backup metadata identity is unsafe")
    dump_bytes = payload.get("dump_bytes")
    captured_epoch_ns = payload.get("captured_at_epoch_ns")
    if (
        isinstance(dump_bytes, bool)
        or not isinstance(dump_bytes, int)
        or dump_bytes <= 0
        or dump_bytes > MAX_DUMP_BYTES
        or dump_bytes != dump_path.stat().st_size
        or isinstance(captured_epoch_ns, bool)
        or not isinstance(captured_epoch_ns, int)
        or captured_epoch_ns <= 0
        or not isinstance(payload.get("dump_sha256"), str)
        or SHA256_RE.fullmatch(payload["dump_sha256"]) is None
        or payload["dump_sha256"] != _sha256(dump_path)
        or not isinstance(payload.get("row_counts"), dict)
        or set(payload["row_counts"]) != set(tables)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in payload["row_counts"].values()
        )
    ):
        raise RestoreProofError("logical backup metadata size or digest does not match")
    started_at = _parse_timestamp(payload.get("capture_started_at"), label="capture start")
    completed_at = _parse_timestamp(payload.get("capture_completed_at"), label="capture completion")
    captured_at = _parse_timestamp(payload.get("captured_at"), label="capture")
    current = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    capture_age = (current - captured_at).total_seconds()
    if (
        completed_at != captured_at
        or started_at > completed_at
        or capture_age < -MAX_CLOCK_SKEW_SECONDS
        or capture_age > MAX_SNAPSHOT_AGE_SECONDS
        or abs(captured_at.timestamp() * 1_000_000_000 - captured_epoch_ns)
        > MAX_CLOCK_SKEW_SECONDS * 1_000_000_000
    ):
        raise RestoreProofError("logical backup metadata timestamps are inconsistent")
    try:
        with dump_path.open("rb") as dump:
            if dump.read(5) != b"PGDMP":
                raise RestoreProofError("logical backup is not a custom-format pg_dump")
    except OSError as error:
        raise RestoreProofError("logical backup could not be read") from error
    return release_id, captured_at, payload["row_counts"]


def _parse_release_env(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RestoreProofError("current application release images are unreadable") from error
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or key in values or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise RestoreProofError("current application release images are malformed")
        values[key] = value
    # Existing immutable releases have three images. Coach is an atomic extra
    # triplet, never a partial or caller-selected image inventory.
    if set(values) not in (RELEASE_IMAGE_KEYS, COACH_RELEASE_IMAGE_KEYS):
        raise RestoreProofError("current application release images have an unexpected contract")
    components = ("ADMIN", "API", "LEARNER")
    if set(values) == COACH_RELEASE_IMAGE_KEYS:
        components += ("COACH",)
    for component in components:
        key = f"AC_{component}_IMAGE"
        if re.fullmatch(r"sha256:[0-9a-f]{64}", values[key]) is None:
            raise RestoreProofError("current application release image identity is unsafe")
    for component in components:
        key = f"AC_{component}_TRANSPORT_DIGEST"
        if re.fullmatch(r"sha256:[0-9a-f]{64}", values[key]) is None:
            raise RestoreProofError("current application transport identity is unsafe")
    for component in components:
        if values[f"AC_{component}_IMAGE"] != values[f"AC_{component}_TRANSPORT_DIGEST"]:
            raise RestoreProofError("current application transport identity is inconsistent")
    for component in components:
        key = f"AC_{component}_REGISTRY_DIGEST"
        if (
            re.fullmatch(
                r"ghcr\.io/authorityclosers/[a-z0-9-]+@sha256:[0-9a-f]{64}",
                values[key],
            )
            is None
        ):
            raise RestoreProofError("current application registry provenance is unsafe")
    if re.fullmatch(r"[0-9]{8}_[0-9]{4}", values["AC_MIGRATION_HEAD"]) is None:
        raise RestoreProofError("current application release migration identity is unsafe")
    if RELEASE_ID_RE.fullmatch(values["AC_RELEASE_ID"]) is None:
        raise RestoreProofError("current application release identity is unsafe")
    return values


def _verify_release_files(release_dir: Path) -> None:
    manifest_path = release_dir / "RELEASE-FILES.sha256"
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or not _owner_is_root(manifest_path)
    ):
        raise RestoreProofError("current application release checksum manifest is unsafe")
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RestoreProofError(
            "current application release checksum manifest is unreadable"
        ) from error
    listed: set[str] = set()
    for line in lines:
        digest, separator, relative = line.partition("  ")
        relative = relative.removeprefix("./")
        relative_path = PurePosixPath(relative)
        candidate = release_dir.joinpath(*relative_path.parts)
        if (
            not separator
            or not SHA256_RE.fullmatch(digest)
            or not relative
            or relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or relative in listed
            or candidate.is_symlink()
            or not candidate.is_file()
            or not _owner_is_root(candidate)
            or _sha256(candidate) != digest
        ):
            raise RestoreProofError("current application release checksum verification failed")
        listed.add(relative)
    actual_files: set[str] = set()
    try:
        for current, directories, files in os.walk(release_dir, followlinks=False):
            for name in (*directories, *files):
                candidate = Path(current) / name
                if candidate.is_symlink() or not _owner_is_root(candidate):
                    raise RestoreProofError("current application release contains an unsafe entry")
                candidate_mode = candidate.lstat().st_mode
                if not stat.S_ISDIR(candidate_mode) and not stat.S_ISREG(candidate_mode):
                    raise RestoreProofError(
                        "current application release contains a non-regular entry"
                    )
                if candidate.is_file() and candidate.name != "RELEASE-FILES.sha256":
                    actual_files.add(candidate.relative_to(release_dir).as_posix())
    except OSError as error:
        raise RestoreProofError("current application release could not be inspected") from error
    if listed != actual_files:
        raise RestoreProofError("current application release contains unmanifested files")


def resolve_current_release(environment: str, root: Path = Path("/")) -> ApplicationRelease:
    if environment not in ENVIRONMENTS:
        raise RestoreProofError("unsupported application environment")
    application_root = (
        root / APPLICATION_ROOT.relative_to("/") if root != Path("/") else APPLICATION_ROOT
    )
    current_link = application_root / f"current-{environment}"
    if current_link.is_symlink() is False or not _owner_is_root(current_link):
        raise RestoreProofError("current immutable application release is missing")
    try:
        release_dir = current_link.resolve(strict=True)
    except OSError as error:
        raise RestoreProofError("current immutable application release is broken") from error
    releases_root = application_root / "releases"
    if (
        release_dir.parent != releases_root
        or RELEASE_ID_RE.fullmatch(release_dir.name) is None
        or release_dir.is_symlink()
        or not release_dir.is_dir()
        or not _owner_is_root(release_dir)
    ):
        raise RestoreProofError("current immutable application release is unsafe")
    _verify_release_files(release_dir)
    images = _parse_release_env(release_dir / "release-images.env")
    parity_tables_for_head(images["AC_MIGRATION_HEAD"])
    if images["AC_RELEASE_ID"] != release_dir.name:
        raise RestoreProofError("current immutable application release identity is inconsistent")
    restore_drill = release_dir / "scripts" / "restore-drill.py"
    if (
        restore_drill.is_symlink()
        or not restore_drill.is_file()
        or not _owner_is_root(restore_drill)
    ):
        raise RestoreProofError("current immutable application restore drill is missing")
    return ApplicationRelease(
        environment=environment,
        release_dir=release_dir,
        restore_drill=restore_drill,
        api_image=images["AC_API_IMAGE"],
        migration_head=images["AC_MIGRATION_HEAD"],
    )


def _restic_path_argument(path: str) -> str:
    return "/" + path


def _restore_pair(snapshot: Snapshot, pair: SnapshotPair, root: Path) -> None:
    _run(
        (
            "restic",
            "restore",
            snapshot.snapshot_id,
            "--target",
            str(root),
            "--include",
            _restic_path_argument(pair.dump_path),
            "--include",
            _restic_path_argument(pair.metadata_path),
        ),
        "Restic logical pair restore",
        timeout_seconds=RESTORE_TIMEOUT_SECONDS,
    )


def _new_evidence_dir(root: Path, environment: str) -> Path:
    _require_directory(root, label="restore evidence root", mode=0o750)
    for _attempt in range(8):
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        candidate = root / f"{environment}-{stamp}-{secrets.token_hex(6)}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise RestoreProofError("restore evidence identity is ambiguous")


def _validate_drill_evidence(evidence_path: Path, evidence_dir: Path) -> None:
    if (
        evidence_dir.is_symlink()
        or not evidence_dir.is_dir()
        or not _owner_is_root(evidence_dir)
        or evidence_path.parent != evidence_dir
        or not EVIDENCE_FILE_RE.fullmatch(evidence_path.name)
        or evidence_path.is_symlink()
        or not evidence_path.is_file()
        or not _owner_is_root(evidence_path)
    ):
        raise RestoreProofError("restore drill evidence path is unsafe")
    if os.name != "nt" and stat.S_IMODE(evidence_path.stat().st_mode) != 0o600:
        raise RestoreProofError("restore drill evidence permissions are unsafe")
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreProofError("restore drill evidence is invalid") from error
    required = {
        "schema",
        "row_counts",
        "invariants_before_hold",
        "restore_marker",
        "worker_hold_proof",
        "cleanup",
        "target",
        "external_connections",
        "operation_gate",
        "objective_gate",
    }
    if not isinstance(payload, Mapping) or not required.issubset(payload):
        raise RestoreProofError("restore drill evidence is incomplete")
    target = payload["target"]
    cleanup = payload["cleanup"]
    worker = payload["worker_hold_proof"]
    operation_gate = payload["operation_gate"]
    objective_gate = payload["objective_gate"]
    if (
        payload.get("result") != "passed"
        or not isinstance(target, Mapping)
        or target.get("published_ports") != []
        or payload.get("external_connections") != []
        or not isinstance(cleanup, Mapping)
        or cleanup.get("status") != "completed"
        or not isinstance(worker, Mapping)
        or worker.get("provider_calls") != 0
        or worker.get("worker_ready") is not False
        or worker.get("run_once_rejected") is not True
        or not isinstance(operation_gate, Mapping)
        or operation_gate.get("status") != "passed"
        or not isinstance(objective_gate, Mapping)
        or objective_gate.get("status") != "passed"
    ):
        raise RestoreProofError("restore drill evidence did not prove the recovery contract")
    entries = list(evidence_dir.iterdir())
    if entries != [evidence_path] and set(entries) != {evidence_path}:
        raise RestoreProofError("restore drill evidence directory is dirty")


def _verify_row_count_parity(
    evidence_path: Path, expected: Mapping[str, int], *, expected_migration_head: str
) -> None:
    tables = parity_tables_for_head(expected_migration_head)
    contract = parity_contract_for_head(expected_migration_head)
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreProofError("restore drill evidence is not readable for parity") from error
    actual = payload.get("row_counts") if isinstance(payload, Mapping) else None
    schema = payload.get("schema") if isinstance(payload, Mapping) else None
    if (
        not isinstance(actual, Mapping)
        or set(actual) != set(tables)
        or dict(actual) != dict(expected)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in actual.values()
        )
        or not isinstance(schema, Mapping)
        or schema.get("expected_migration_head") != expected_migration_head
        or schema.get("actual_migration_versions") != [expected_migration_head]
        or schema.get("canonical_tables_checked") != len(tables)
        or (contract is not None and payload.get("parity_contract") != contract)
    ):
        raise RestoreProofError("restored critical-table row-count parity failed")


def _invoke_restore_drill(
    release: ApplicationRelease,
    environment: str,
    dump_path: Path,
    metadata_path: Path,
    evidence_dir: Path,
) -> Path:
    result = _run(
        (
            "python3",
            str(release.restore_drill),
            "--environment",
            environment,
            "--backup",
            str(dump_path),
            "--backup-metadata",
            str(metadata_path),
            "--evidence-dir",
            str(evidence_dir),
            "--application-image",
            release.api_image,
            "--execute",
            "--acknowledge-isolated-target",
        ),
        "disposable PostgreSQL restore drill",
        timeout_seconds=DRILL_TIMEOUT_SECONDS,
        capture_stdout=True,
    )
    try:
        summary = json.loads(result)
    except json.JSONDecodeError as error:
        raise RestoreProofError("restore drill returned invalid evidence summary") from error
    if not isinstance(summary, Mapping) or summary.get("result") != "passed":
        raise RestoreProofError("disposable PostgreSQL restore drill failed")
    evidence_value = summary.get("evidence")
    if not isinstance(evidence_value, str):
        raise RestoreProofError("restore drill did not return an evidence path")
    evidence_path = Path(evidence_value)
    _validate_drill_evidence(evidence_path, evidence_dir)
    return evidence_path


def run(
    environment: str,
    *,
    restore_root: Path = RESTORE_ROOT,
    evidence_root: Path = EVIDENCE_ROOT,
    now: dt.datetime | None = None,
) -> Path:
    """Run one environment's proof and return its safe evidence directory."""

    if os.name != "nt" and os.geteuid() != 0:
        raise RestoreProofError("off-site logical restore proof must run as root")
    if environment not in ENVIRONMENTS:
        raise RestoreProofError("unsupported application environment")
    release = resolve_current_release(environment)
    snapshots_json = _run(
        (
            "restic",
            "snapshots",
            "--json",
            "--tag",
            f"{RESTIC_TAG},environment={environment}",
        ),
        "Restic logical snapshot listing",
        timeout_seconds=SNAPSHOT_TIMEOUT_SECONDS,
        capture_stdout=True,
    )
    snapshot = select_latest_snapshot(snapshots_json, environment, now=now)
    tree_json = _run(
        ("restic", "ls", "--json", snapshot.snapshot_id),
        "Restic logical snapshot tree listing",
        timeout_seconds=SNAPSHOT_TIMEOUT_SECONDS,
        capture_stdout=True,
    )
    pair = select_snapshot_pair(tree_json, environment, snapshot.snapshot_id)
    restore_dir = create_restore_directory(restore_root)
    stable_dir: Path | None = None
    evidence_dir: Path | None = None
    try:
        evidence_dir = _new_evidence_dir(evidence_root, environment)
        _restore_pair(snapshot, pair, restore_dir)
        restored_dump, restored_metadata = _verify_restored_pair(restore_dir, pair)
        release_id, captured_at, expected_counts = _validate_metadata(
            restored_metadata,
            restored_dump,
            environment,
            expected_migration_head=release.migration_head,
            now=now,
        )
        if release_id != release.release_dir.name:
            raise RestoreProofError(
                "logical backup release does not match the current immutable release"
            )
        validate_snapshot_capture_timing(snapshot, captured_at, now=now)
        stable_dir, dump_path, metadata_path = copy_stable_pair(
            restored_dump, restored_metadata, restore_root
        )
        stable_release_id, _stable_captured_at, _stable_counts = _validate_metadata(
            metadata_path,
            dump_path,
            environment,
            expected_migration_head=release.migration_head,
            now=now,
        )
        if stable_release_id != release.release_dir.name:
            raise RestoreProofError(
                "stable logical backup release does not match the current immutable release"
            )
        if evidence_dir is None:
            raise RestoreProofError("restore evidence directory was not prepared")
        drill_evidence = _invoke_restore_drill(
            release, environment, dump_path, metadata_path, evidence_dir
        )
        _verify_row_count_parity(
            drill_evidence, expected_counts, expected_migration_head=release.migration_head
        )
        _write_proof_record(
            evidence_dir,
            snapshot,
            pair,
            dump_path,
            metadata_path,
            release,
            drill_evidence,
        )
        return evidence_dir
    finally:
        cleanup_errors: list[RestoreProofError] = []
        for cleanup_path in (stable_dir, restore_dir):
            if cleanup_path is None:
                continue
            try:
                remove_restore_directory(cleanup_path, restore_root)
            except RestoreProofError as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            raise RestoreProofError("bounded logical restore cleanup failed") from cleanup_errors[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        environment = build_parser().parse_args(argv).environment
        evidence_dir = run(environment)
        print(
            json.dumps(
                {
                    "environment": environment,
                    "evidence_directory": str(evidence_dir),
                    "result": "passed",
                },
                sort_keys=True,
            )
        )
        return 0
    except RestoreProofError as error:
        print(f"off-site logical restore proof failed closed: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # pragma: no cover - final fail-closed boundary
        print(
            f"off-site logical restore proof failed closed: unexpected {type(error).__name__}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

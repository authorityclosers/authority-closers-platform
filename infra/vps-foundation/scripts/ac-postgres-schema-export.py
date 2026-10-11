#!/usr/bin/env python3
"""Export a staging schema for migration CI, using the backup snapshot protocol."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ac_schema_export_backup", Path(__file__).with_name("ac-postgres-backup.py")
)
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup
SPEC.loader.exec_module(backup)
MAX_BYTES = 32 * 1024 * 1024


def schema_dump_command(target: backup.ApplicationTarget, snapshot_id: str) -> list[str]:
    if target.environment != "staging":
        raise backup.BackupError("Schema evidence may only be exported from staging.")
    command = backup.dump_command(target, snapshot_id)
    # Reuse the existing credential transport, timeout and snapshot binding.
    original = "--format=custom --create"
    if command[-1].count(original) != 1:
        raise backup.BackupError("The backup dump command contract has changed.")
    command[-1] = command[-1].replace(
        original, "--format=custom --schema-only --no-owner --no-acl --lock-wait-timeout=2s"
    )
    return command


def snapshot_metadata(target: backup.ApplicationTarget, snapshot_id: str) -> tuple[int, str]:
    snapshot_id = backup.validate_exported_snapshot_id(snapshot_id)
    query = (
        "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY; "  # noqa: S608 - snapshot ID validated above
        f"SET TRANSACTION SNAPSHOT '{snapshot_id}'; "
        "SELECT current_setting('server_version_num'), version_num FROM alembic_version; "
        "COMMIT;"
    )
    command = backup.compose_command(
        target,
        "exec",
        "-T",
        "postgres",
        "sh",
        "-euc",
        'export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
        "exec psql --no-password -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 "
        '-U ac_backup -d "$POSTGRES_DB" -c "$1"',
        "--",
        query,
    )
    result = backup.run_checked(command, target=target).stdout.strip()
    if not re.fullmatch(r"[0-9]{6}\|[0-9]{8}_[0-9]{4}", result):
        raise backup.BackupError("Schema snapshot must have one PostgreSQL version and revision.")
    version, revision = result.split("|")
    if revision != target.migration_head:
        raise backup.BackupError("Schema snapshot differs from the exact staging release.")
    return int(version), revision


def export_schema(target: backup.ApplicationTarget, output: Path) -> dict[str, object]:
    if target.environment != "staging":
        raise backup.BackupError("Schema evidence may only be exported from staging.")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    dump = output / "schema.dump"
    manifest = output / "manifest.json"
    holder = None
    process = None
    try:
        holder = backup.start_exported_snapshot_holder(target)
        version, revision = snapshot_metadata(target, holder.snapshot_id)
        holder.assert_alive()
        process = subprocess.Popen(  # noqa: S603 - fixed backup transport and schema-only flags
            schema_dump_command(target, holder.snapshot_id),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=backup.compose_environment(target),
            start_new_session=(os.name == "posix"),
        )
        assert process.stdout is not None
        size = 0
        digest = hashlib.sha256()
        with dump.open("xb") as destination:
            dump.chmod(0o600)
            while chunk := process.stdout.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise backup.BackupError("Schema export exceeded 32 MiB.")
                digest.update(chunk)
                destination.write(chunk)
        if process.wait(timeout=backup.PG_DUMP_KILL_AFTER_SECONDS) != 0 or not size:
            raise backup.BackupError("Schema export failed or was empty.")
        holder.assert_alive()
        holder.close()
        holder = None
        metadata: dict[str, object] = {
            "schema": "ac.migration_schema/1",
            "environment": "staging",
            "schema_only": True,
            "postgres_version_num": version,
            "alembic_revision": revision,
            "exported_at": backup.timestamp(),
            "dump_sha256": digest.hexdigest(),
            "release_id": target.release_dir.name,
        }
        with manifest.open("x", encoding="utf-8") as destination:
            manifest.chmod(0o600)
            destination.write(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
        return metadata
    except BaseException:
        if process is not None and process.poll() is None:
            backup.terminate_process(process)
        dump.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        output.rmdir()
        raise
    finally:
        if holder is not None:
            holder.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new, absolute export directory")
    parser.add_argument("--apply", action="store_true", help="export; otherwise validate only")
    args = parser.parse_args()
    try:
        if not args.output.is_absolute() or args.output.exists():
            raise backup.BackupError("Use a new absolute export directory.")
        if os.geteuid() != 0:
            raise backup.BackupError("The staging export uses the governed root backup operator.")
        target = backup.resolve_application_release("staging")
        if target is None:
            raise backup.BackupError("The exact staging release is unavailable.")
        backup.assert_healthy(target)
        with backup.environment_lock("staging", Path("/")):
            if args.apply:
                export_schema(target, args.output)
        print(
            "schema-export: PASS (schema-only export)"
            if args.apply
            else "schema-export: dry-run OK"
        )
        return 0
    except (backup.BackupError, OSError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, backup.BackupError) else "Bounded export failed."
        print(f"schema-export: FAIL ({message})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Pinned, content-free PostgreSQL sizing; validate only unless --read is supplied."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

APP_SHA = "fa846dc1264130e295eccc13daf6164c673c8a8a"
BACKUP_SHA256 = "fea361c9883d603b0fae78c8081b4492be965afeb65ac619448ca2556aa294cf"
POLICY_SHA256 = "bd04b1397a802ec8923e3e488d3b1a2fea8454219aae4ea19ad5ee151ce84846"
SCHEMA_HEAD = "20261011_0087"
PARITY_CONTRACT = "ac-postgres-parity-v58"
POSTGRES_VERSION_NUM = 180006
BACKUP_SOURCE = Path("/usr/local/libexec/authority-closers/ac-postgres-backup.py")
MAX_RECORDS = 1024
MAX_OUTPUT_BYTES = 1024 * 1024
TOTAL_SECONDS = 60
REMOTE_SECONDS = 55
LOCK_TIMEOUT_MS = 1000
STATEMENT_TIMEOUT_MS = 10000
MAX_INTEGER = 2**63 - 1
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")


class Refusal(RuntimeError):
    """Only a fixed reason code, never subprocess output or exception text."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bounded_file(path: Path, limit: int = MAX_OUTPUT_BYTES) -> bytes:
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise Refusal("file_limit")
    return data


def inventory(backup: types.ModuleType) -> tuple[str, ...]:
    tables = tuple(backup.parity_tables_for_head(SCHEMA_HEAD))
    if (
        not tables
        or len(tables) > MAX_RECORDS
        or len(set(tables)) != len(tables)
        or any(not IDENTIFIER.fullmatch(t) for t in tables)
        or "alembic_version" not in tables
        or backup.parity_contract_for_head(SCHEMA_HEAD) != PARITY_CONTRACT
    ):
        raise Refusal("inventory_drift")
    return tables


def load_backup(path: Path = BACKUP_SOURCE) -> types.ModuleType:
    # Execute only bytes whose digest is already approved, without pycache writes.
    data = bounded_file(path)
    if sha256(data) != BACKUP_SHA256:
        raise Refusal("backup_drift")
    module = types.ModuleType("ac_sizing_pinned_backup")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(data, str(path), "exec"), module.__dict__)  # noqa: S102 - digest-pinned source
    inventory(module)
    return module


def admit(backup: types.ModuleType, environment: str, host_root: Path = Path("/")) -> Any:
    # Reuse the release checksum/profile and backup-scope policy contracts.
    scope = backup.host_path(host_root, backup.FOUNDATION_SCOPES / "backup.release")
    if scope.is_symlink() or bounded_file(scope, 128) != f"foundation-{APP_SHA}\n".encode():
        raise Refusal("backup_scope_drift")
    policy = backup.foundation_policy_path(host_root)
    if sha256(bounded_file(policy, 65536)) != POLICY_SHA256:
        raise Refusal("policy_drift")
    backup.projected_logical_bytes(backup.read_policy(policy))
    target = backup.resolve_application_release(environment, host_root=host_root)
    if target is None or target.release_dir.name != APP_SHA or target.migration_head != SCHEMA_HEAD:
        raise Refusal("application_drift")
    return target


def fixed_sql(tables: tuple[str, ...]) -> bytes:
    if (
        not tables
        or len(tables) > MAX_RECORDS
        or len(set(tables)) != len(tables)
        or "alembic_version" not in tables
        or any(not IDENTIFIER.fullmatch(t) for t in tables)
    ):
        raise Refusal("inventory_drift")
    names = ",".join(f"'{table}'" for table in tables)
    # One repeatable-read transaction: the initial admission acquires its snapshot.
    # Exact public-table inventory follows the existing restore parity contract.
    sql = f"""BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;
SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms';
SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms';
SET LOCAL idle_in_transaction_session_timeout = '5000ms';
SET LOCAL search_path = pg_catalog;
SET LOCAL timezone = 'UTC';
SET LOCAL row_security = off;
WITH relations AS (
 SELECT c.oid, c.relname, c.relkind FROM pg_class c
 JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')
 ORDER BY c.relname LIMIT {MAX_RECORDS + 1}
), tables AS (SELECT * FROM relations)
SELECT 1 / (
 current_user = 'ac_backup'
 AND current_setting('transaction_read_only') = 'on'
 AND current_setting('transaction_isolation') = 'repeatable read'
 AND current_setting('server_version_num')::int = {POSTGRES_VERSION_NUM}
 AND EXISTS (SELECT FROM pg_roles WHERE rolname = current_user
   AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit
   AND NOT rolreplication AND NOT rolbypassrls)
 AND has_schema_privilege('public','USAGE')
 AND (SELECT count(*) FROM tables) = {len(tables)}
 AND NOT EXISTS (SELECT FROM tables WHERE relkind <> 'r' OR relname NOT IN ({names}))
 AND NOT EXISTS (SELECT FROM tables WHERE
   NOT has_table_privilege(oid,'SELECT')
   OR has_table_privilege(oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
)::int;
SELECT 1 / coalesce((count(*) = 1 AND bool_and(version_num = '{SCHEMA_HEAD}'))::int, 0)
FROM public.alembic_version;
SELECT json_build_object('kind','database','started_at',
 to_char(clock_timestamp(),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
 'database_bytes',pg_database_size(current_database()),
 'postgres_version_num',current_setting('server_version_num')::int,
 'read_only',current_setting('transaction_read_only') = 'on');
"""  # noqa: S608 - identifiers and pins from the reviewed versioned inventory only
    for table in tables:
        sql += f"""SELECT json_build_object('kind','relation','relation','{table}',
 'heap_bytes',pg_relation_size('public.{table}'::regclass),
 'index_bytes',pg_indexes_size('public.{table}'::regclass),
 'total_bytes',pg_total_relation_size('public.{table}'::regclass),
 'parity_count',count(*)) FROM public."{table}";
"""  # noqa: S608 - fixed canonical allowlist, never caller SQL
    sql += """SELECT json_build_object('kind','end','finished_at',
 to_char(clock_timestamp(),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
ROLLBACK;
"""
    return sql.encode("ascii")


def operation_clock() -> float:
    # Linux Docker shares this kernel clock, also exposed by /proc/uptime.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def remote_guard(deadline: float, command: str) -> str:
    if not math.isfinite(deadline) or deadline <= 0:
        raise Refusal("total_timeout")
    clock_namespace = os.readlink("/proc/self/ns/time")
    if not re.fullmatch(r"time:\[[0-9]+\]", clock_namespace):
        raise Refusal("clock_unavailable")
    ticks = math.floor(deadline * 100)
    # Recompute remaining time after transport, then watch the absolute deadline
    # throughout execution. The relative watchdog is an additional 55s ceiling.
    return f"""[ "$(readlink /proc/self/ns/time)" = '{clock_namespace}' ] || exit 3
budget() {{
 awk -v end={ticks} -v cap={REMOTE_SECONDS} 'NR == 1 {{
   left=end/100-$1-1; if (left<=0) exit 3;
   printf "%.2f", (left<cap ? left : cap)
 }}' /proc/uptime
}}
duration=$(budget) || exit 3
exec 3<&0
timeout --signal=KILL "${{duration}}s" {command} <&3 &
reader=$!
exec 3<&-
cleanup() {{
 kill -KILL "-$reader" 2>/dev/null || kill -KILL "$reader" 2>/dev/null || :
 wait "$reader" 2>/dev/null || :
}}
trap cleanup EXIT
trap 'exit 3' HUP INT TERM
while kill -0 "$reader" 2>/dev/null; do
 budget >/dev/null || exit 3
 sleep 0.05
done
wait "$reader"
"""


def diagnostic_command(backup: types.ModuleType, target: Any, deadline: float) -> list[str]:
    # Credentials stay inside the existing Infisical/compose runtime injection.
    # A remote watchdog is necessary: killing a Docker client alone leaves exec alive.
    return backup.compose_command(
        target,
        "exec",
        "-T",
        "postgres",
        "sh",
        "-euc",
        "unset PGHOST PGHOSTADDR PGPORT PGUSER PGDATABASE "
        "PGSERVICE PGSERVICEFILE PGOPTIONS PGPASSFILE; "
        'export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
        "export PGCONNECT_TIMEOUT=2 PGAPPNAME=ac-postgres-sizing; "
        + remote_guard(
            deadline,
            "psql --no-password --no-psqlrc --set=ON_ERROR_STOP=1 "
            '-h 127.0.0.1 -p 5432 -U ac_backup -d "$POSTGRES_DB" -qAt -f -',
        ),
    )


def terminate_group(process: subprocess.Popen[bytes]) -> None:
    # Kill the entire owned group, even if its leader exited leaving pipe holders.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=1)


def bounded_process(
    command: list[str],
    sql: bytes,
    environment: dict[str, str],
    deadline: float,
    scratch: Path | None = None,
) -> bytes:
    process = None
    result = bytearray()
    try:
        scratch = scratch or Path(
            os.environ.get("PAPERCLIP_RUN_SCRATCH_DIR")
            or os.environ.get("PAPERCLIP_SCRATCH_DIR", "")
        )
        if not scratch.is_absolute():
            raise Refusal("scratch_unavailable")
        if deadline - operation_clock() <= 1:
            raise Refusal("total_timeout")
        with (
            tempfile.TemporaryFile(dir=scratch) as input_file,
            selectors.DefaultSelector() as selector,
        ):
            input_file.write(sql)
            input_file.seek(0)
            process = subprocess.Popen(  # noqa: S603 - fixed reviewed runtime command
                command,
                stdin=input_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - operation_clock()
                if remaining <= 1:  # reserve one second for forced cleanup
                    raise Refusal("total_timeout")
                for key, _ in selector.select(remaining - 1):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stderr:
                        raise Refusal("database_refused")
                    result.extend(chunk)
                    if len(result) > MAX_OUTPUT_BYTES:
                        raise Refusal("output_limit")
            remaining = deadline - operation_clock()
            if remaining <= 1:
                raise Refusal("total_timeout")
            if process.wait(timeout=remaining - 1) != 0:
                raise Refusal("database_refused")
        return bytes(result)
    except (OSError, subprocess.SubprocessError):
        raise Refusal("process_refused") from None
    finally:
        if process is not None:
            terminate_group(process)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def decode_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("unsafe_result")
        result[key] = value
    return result


def valid_integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_INTEGER


def timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise Refusal("unsafe_result")
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Refusal("unsafe_result") from None


def validate_output(data: bytes, tables: tuple[str, ...]) -> dict[str, Any]:
    if len(data) > MAX_OUTPUT_BYTES or len(tables) > MAX_RECORDS:
        raise Refusal("output_limit")
    try:
        lines = data.decode("ascii").splitlines()
        # The two admission statements emit exactly one fixed scalar each.
        if len(lines) != len(tables) + 4 or lines[:2] != ["1", "1"]:
            raise Refusal("unsafe_result")
        records = [json.loads(line, object_pairs_hook=decode_object) for line in lines[2:]]
        if any(type(record) is not dict for record in records):
            raise Refusal("unsafe_result")
        first, last = records[0], records[-1]
        if (
            set(first)
            != {"kind", "started_at", "database_bytes", "postgres_version_num", "read_only"}
            or first["kind"] != "database"
            or first["read_only"] is not True
            or type(first["postgres_version_num"]) is not int
            or first["postgres_version_num"] != POSTGRES_VERSION_NUM
            or not valid_integer(first["database_bytes"])
            or set(last) != {"kind", "finished_at"}
            or last["kind"] != "end"
        ):
            raise Refusal("unsafe_result")
        started, finished = timestamp(first["started_at"]), timestamp(last["finished_at"])
        if not 0 <= (finished - started).total_seconds() <= TOTAL_SECONDS:
            raise Refusal("unsafe_result")
        for table, record in zip(tables, records[1:-1], strict=True):
            if (
                set(record)
                != {"kind", "relation", "heap_bytes", "index_bytes", "total_bytes", "parity_count"}
                or record["kind"] != "relation"
                or record["relation"] != table
                or any(
                    not valid_integer(record[key])
                    for key in ("heap_bytes", "index_bytes", "total_bytes", "parity_count")
                )
                or record["total_bytes"] < record["heap_bytes"] + record["index_bytes"]
            ):
                raise Refusal("unsafe_result")
        return {
            "started_at": first["started_at"],
            "finished_at": last["finished_at"],
            "database_bytes": first["database_bytes"],
            "relations": records[1:-1],
        }
    except (ValueError, UnicodeError, KeyError, TypeError, RecursionError, OverflowError):
        raise Refusal("unsafe_result") from None


@contextlib.contextmanager
def operation_limit() -> Iterator[float]:
    def interrupt(signum: int, _frame: Any) -> None:
        raise Refusal("total_timeout" if signum == signal.SIGALRM else "cancelled")

    previous = {
        s: signal.signal(s, interrupt) for s in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM)
    }
    previous_timer = signal.setitimer(signal.ITIMER_REAL, TOTAL_SECONDS)
    try:
        yield operation_clock() + TOTAL_SECONDS
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def receipt(
    pins: dict[str, str], tables: tuple[str, ...], measurements: dict[str, Any] | None
) -> bytes:
    sql = fixed_sql(tables)
    result = {
        "schema": "ac.postgres_sizing/1",
        "mode": "read" if measurements else "dry_run",
        "pins": {
            **pins,
            "app_sha": APP_SHA,
            "backup_sha": APP_SHA,
            "backup_sha256": BACKUP_SHA256,
            "policy_sha256": POLICY_SHA256,
            "schema_head": SCHEMA_HEAD,
            "parity_contract": PARITY_CONTRACT,
            "inventory_sha256": sha256(json.dumps(list(tables), separators=(",", ":")).encode()),
            "sql_sha256": sha256(sql),
        },
        "limits": {
            "relations": MAX_RECORDS,
            "output_bytes": MAX_OUTPUT_BYTES,
            "lock_timeout_ms": LOCK_TIMEOUT_MS,
            "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            "total_seconds": TOTAL_SECONDS,
            "remote_seconds": REMOTE_SECONDS,
        },
        "approved_relations": len(tables),
        "postgres_version_num": POSTGRES_VERSION_NUM,
        "counts_consistency": "one-repeatable-read-snapshot",
        "bytes_semantics": "contemporaneous-storage-observations",
        "application_mutations": 0,
        "measurements": measurements,
    }
    data = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_OUTPUT_BYTES:
        raise Refusal("output_limit")
    return data


def validate_scratch(path: Path | None) -> Path:
    run = os.environ.get("PAPERCLIP_RUN_ID", "")
    if path is None or not path.is_absolute() or not re.fullmatch(r"[0-9a-f-]{36}", run):
        raise Refusal("scratch_unavailable")
    if (
        path.resolve(strict=True) != path
        or not path.is_dir()
        or path.stat().st_mode & 0o022
        or Path(__file__).is_symlink()
        or Path(__file__).resolve().parent != path
        or path.stat().st_uid != Path(__file__).stat().st_uid
        or not any(run in p.name or run[:12] in p.name for p in (path, *path.parents))
    ):
        raise Refusal("scratch_unsafe")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("production", "staging"), default="production")
    parser.add_argument(
        "--source-sha", required=True, help="independently reviewed full source commit"
    )
    parser.add_argument(
        "--script-sha256", required=True, help="independently reviewed script digest"
    )
    parser.add_argument(
        "--read", action="store_true", help="one authorised read; default is validation only"
    )
    parser.add_argument(
        "--scratch-dir", type=Path, help="run-owned script directory; required for read"
    )
    args = parser.parse_args()
    try:
        with operation_limit() as deadline:
            if (
                not re.fullmatch(r"[0-9a-f]{40}", args.source_sha)
                or not re.fullmatch(r"[0-9a-f]{64}", args.script_sha256)
                or sha256(bounded_file(Path(__file__))) != args.script_sha256
            ):
                raise Refusal("source_drift")
            backup = load_backup()
            tables = inventory(backup)
            target = admit(backup, args.environment)
            measurements = None
            if args.read:
                scratch = validate_scratch(args.scratch_dir)
                output = bounded_process(
                    diagnostic_command(backup, target, deadline),
                    fixed_sql(tables),
                    backup.compose_environment(target),
                    deadline,
                    scratch,
                )
                measurements = validate_output(output, tables)
                # Refuse a release/policy switch during the observation, too.
                admit(backup, args.environment)
            data = receipt(
                {
                    "source_sha": args.source_sha,
                    "script_sha256": args.script_sha256,
                    "environment": args.environment,
                },
                tables,
                measurements,
            )
            if operation_clock() >= deadline:
                raise Refusal("total_timeout")
            sys.stdout.buffer.write(data)
        return 0
    except Refusal as error:
        print(f"postgres-sizing: REFUSED ({error})", file=sys.stderr)
    except Exception:
        # Backup/OS/parser exceptions may contain paths, DSNs or credential-bearing diagnostics.
        print("postgres-sizing: REFUSED (admission_or_runtime)", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

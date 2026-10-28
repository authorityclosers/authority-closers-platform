#!/usr/bin/env python3
# ruff: noqa: S603, S607, E501 -- reviewed argv, fixed utilities, no shell interpolation
"""Private host adapter: Docker PostgreSQL I/O and durable file inventories.

Never put passwords in arguments. Production destructive restore needs a separate
explicit flag, in addition to the driver's configuration-bound approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

LOGIN = 'export PGPASSWORD="$POSTGRES_PASSWORD"; '
PSQL = 'exec psql -X -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1" -At -v ON_ERROR_STOP=1'
COUNTS = r"""
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT format('SELECT json_build_array(''table'', %L, %L, count(*)) FROM %I.%I;', schemaname, tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname, tablename
\gexec
SELECT format('SELECT json_build_array(''sequence'', %L, %L, last_value, is_called) FROM %I.%I;', schemaname, sequencename, schemaname, sequencename)
FROM pg_sequences WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname, sequencename
\gexec
SELECT json_build_array('column', table_schema, table_name, column_name, data_type, is_nullable, column_default)
FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_schema, table_name, ordinal_position;
SELECT json_build_array('rls', n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname NOT IN ('pg_catalog','information_schema') ORDER BY n.nspname,c.relname;
SELECT json_build_array('policy', schemaname, tablename, policyname, roles, cmd, qual, with_check) FROM pg_policies ORDER BY schemaname,tablename,policyname;
SELECT json_build_array('constraint', n.nspname, c.relname, con.conname, pg_get_constraintdef(con.oid))
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema') ORDER BY n.nspname,c.relname,con.conname;
SELECT json_build_array('index', schemaname, tablename, indexname, indexdef)
FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname,tablename,indexname;
SELECT json_build_array('extension', extname, extversion) FROM pg_extension ORDER BY extname;
SELECT json_build_array('grant', table_schema, table_name, grantee, privilege_type, is_grantable)
FROM information_schema.role_table_grants WHERE table_schema NOT IN ('pg_catalog','information_schema')
ORDER BY table_schema,table_name,grantee,privilege_type;
SELECT json_build_array('role', rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls, rolconnlimit)
FROM pg_roles WHERE rolname IN ('ac_owner','ac_runtime','ac_migrator','ac_backup') ORDER BY rolname;
SELECT json_build_array('schema-head', version_num) FROM public.alembic_version ORDER BY version_num;
COMMIT;
"""


def docker(container, script, db, data=None):
    r = subprocess.run(
        [
            "nice",
            "-n",
            "19",
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-euc",
            LOGIN + script,
            "cutover",
            db,
        ],
        input=data,
        capture_output=True,
        check=False,
        timeout=600,
    )
    if r.returncode:
        raise RuntimeError("database operation failed")
    return r.stdout


def manifest(root, ownership=False):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("unsafe root")
    result = {}
    device = root.stat().st_dev
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".cutover-partial")
        for name in dirs + sorted(files):
            p = Path(base) / name
            s = p.lstat()
            if s.st_dev != device or p.is_symlink() or not (p.is_dir() or p.is_file()):
                raise RuntimeError(
                    "links, devices and mount crossings require an explicit inventory"
                )
            if p.is_file():
                with p.open("rb") as f:
                    digest = hashlib.file_digest(f, "sha256").hexdigest()
                after = p.stat()
                if (s.st_size, s.st_mtime_ns, s.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise RuntimeError("file changed during inventory")
                result[str(p.relative_to(root))] = [s.st_size, digest, stat.S_IMODE(s.st_mode)] + (
                    [s.st_uid, s.st_gid] if ownership else []
                )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    f = sub.add_parser("manifest")
    f.add_argument("--ownership", action="store_true")
    f.add_argument("root")
    d = sub.add_parser("database")
    d.add_argument("--permit-production-restore", action="store_true")
    d.add_argument("container")
    d.add_argument("database")
    d.add_argument("action", choices=["dump", "restore", "counts", "capacity"])
    args = p.parse_args()
    if args.kind == "manifest":
        print(json.dumps(manifest(args.root, args.ownership), sort_keys=True))
        return
    if (
        args.action == "restore"
        and not args.database.startswith("cutover_fixture_")
        and not args.permit_production_restore
    ):
        raise RuntimeError("restore requires explicit production permit")
    if args.action == "capacity":
        query = b"SELECT json_build_object('server_version_num', current_setting('server_version_num'), 'max_connections', current_setting('max_connections'), 'max_locks_per_transaction', current_setting('max_locks_per_transaction'), 'max_prepared_transactions', current_setting('max_prepared_transactions'));"
        sys.stdout.buffer.write(docker(args.container, PSQL, args.database, query))
    elif args.action == "dump":
        sys.stdout.buffer.write(
            docker(
                args.container,
                'exec pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1" -Fc',
                args.database,
            )
        )
    elif args.action == "restore":
        data = sys.stdin.buffer.read()
        if not data.startswith(b"PGDMP"):
            raise RuntimeError("custom dump required")
        docker(
            args.container,
            'exec pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1" --clean --if-exists --exit-on-error --single-transaction',
            args.database,
            data,
        )
    else:
        lines = docker(args.container, PSQL, args.database, COUNTS.encode()).decode().splitlines()
        records = [json.loads(line) for line in lines if line.startswith("[")]
        print(
            json.dumps(
                {
                    "tables": [r for r in records if r[0] == "table"],
                    "catalog": [r for r in records if r[0] != "table"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("endpoint failed; diagnostics suppressed", file=sys.stderr)
        sys.exit(1)

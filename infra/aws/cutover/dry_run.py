#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""Whole fictional sequence; never stops/restarts the existing rehearsal stack.

Creates two new databases in its PostgreSQL engine and two tiny loopback fixture
services; restores production-shaped schema, not the app's existing database.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(argv, data=None):
    r = subprocess.run(argv, input=data, capture_output=True, check=False, timeout=900)
    if r.returncode:
        raise RuntimeError("fictional rehearsal command failed; inspect private evidence")
    return r.stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--identity", required=True)
    p.add_argument("--evidence", required=True)
    args = p.parse_args()
    os.umask(0o077)
    root = Path(args.evidence).resolve()
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    tag = uuid.uuid4().hex[:10]
    remote = "/home/ubuntu/cutover-fixture-" + tag
    host = "ubuntu@3.25.123.75"
    ssh = ["ssh", "-o", "BatchMode=yes", "-i", str(Path(args.identity).expanduser()), host]

    def remote_run(argv, data=None):
        return run(ssh + [shlex.join(argv)], data)

    remote_run(["test", "-f", "/home/ubuntu/rehearsal/FICTIONAL-ONLY"])
    remote_run(["mkdir", "-m", "700", remote])
    for name in ["endpoint.py", "fixture.py", "backup.py"]:
        remote_run(["tee", remote + "/" + name], (ROOT / name).read_bytes())
    source_db, target_db = (
        "cutover_fixture_" + tag + "_source",
        "cutover_fixture_" + tag + "_target",
    )

    def sql(db, data):
        return remote_run(
            [
                "docker",
                "exec",
                "-i",
                "ac-rehearsal-postgres-1",
                "sh",
                "-euc",
                'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1" -At -v ON_ERROR_STOP=1',  # noqa: E501 -- literal SQL or fixed remote shell script
                "fixture",
                db,
            ],
            data,
        )

    sql("postgres", f"CREATE DATABASE {source_db};\nCREATE DATABASE {target_db};".encode())
    # No real or existing fixture rows are copied. Schema only from the isolated app.
    schema = remote_run(
        [
            "docker",
            "exec",
            "ac-rehearsal-postgres-1",
            "sh",
            "-euc",
            'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d ac_platform --schema-only --no-owner --no-privileges',  # noqa: E501 -- literal SQL or fixed remote shell script
        ]
    )
    sql(source_db, schema)
    head = sql("ac_platform", b"SELECT version_num FROM alembic_version ORDER BY version_num;")
    for revision in head.decode().splitlines():
        if not revision.replace("_", "").isalnum():
            raise ValueError("invalid fictional schema revision")
        sql(
            source_db,
            f"INSERT INTO alembic_version(version_num) VALUES ('{revision}');".encode(),  # noqa: S608 -- strictly alphanumeric/underscore revision
        )
    sql(
        source_db,
        b"CREATE TABLE cutover_writes(id bigserial PRIMARY KEY,note text NOT NULL); INSERT INTO cutover_writes(note) SELECT 'fictional row ' || n FROM generate_series(1,10000) n;",  # noqa: E501 -- literal SQL or fixed remote shell script
    )
    ports = [18191, 18192]
    for db, port in zip((source_db, target_db), ports, strict=True):
        # Fixed dedicated loopback fixture ports: occupied ports fail closed.
        script = shlex.join(
            ["python3", remote + "/fixture.py", "serve", "--database", db, "--port", str(port)]
        )
        remote_run(
            [
                "sh",
                "-c",
                f"nohup nice -n 19 {script} >{remote}/service-{port}.log 2>&1 < /dev/null & echo $! >{remote}/service-{port}.pid",  # noqa: E501 -- literal SQL or fixed remote shell script
            ]
        )

    def hook(side, op):
        return ssh + [
            shlex.join(
                [
                    "python3",
                    remote + "/fixture.py",
                    "hook",
                    "--database",
                    source_db if side == "source" else target_db,
                    "--port",
                    str(ports[0 if side == "source" else 1]),
                    "--operation",
                    op,
                ]
            )
        ]

    for _ in range(30):
        try:
            run(hook("source", "held-canary"))
            run(hook("target", "held-canary"))
            break
        except RuntimeError:
            time.sleep(0.2)
    else:
        raise RuntimeError("fixture services unavailable")
    run(hook("source", "open"))
    config = {
        "environment": "fictional",
        "freeze_budget_seconds": 600,
        "step_timeout": 600,
        "files": [],
        "hooks": {},
        "rsync_ssh": shlex.join(ssh[:-1]),
        "bwlimit_kib": 4096,
    }
    for side, db in [("source", source_db), ("target", target_db)]:
        config[side] = {
            "database": ssh
            + [
                shlex.join(
                    ["python3", remote + "/endpoint.py", "database", "ac-rehearsal-postgres-1", db]
                )
            ]
        }
        config[side]["manifest"] = (
            [sys.executable, str(ROOT / "endpoint.py"), "manifest"]
            if side == "source"
            else ssh + [shlex.join(["python3", remote + "/endpoint.py", "manifest"])]
        )
        config[side]["host"] = "" if side == "source" else host
        for action, op in [
            ("hold_", "hold"),
            ("drain_", "drain"),
            ("fence_", "fence"),
            ("open_", "open"),
        ]:
            config["hooks"][action + side] = hook(side, op)
        config["hooks"]["start_" + side + "_held"] = hook(side, "start-held")
        config["hooks"][side + "_held_canary"] = hook(side, "held-canary")
        config["hooks"][side + "_canary"] = hook(side, "canary")
    for kind in ["recordings", "media", "spool"]:
        local = root / "source-files" / kind
        local.mkdir(parents=True)
        # 12 MiB total; fictional bytes only, resumable SSH copy measurable.
        for n in range(8):
            (local / f"fictional-{n}.bin").write_bytes(bytes([n]) * 524288)
        target = remote + "/files/" + kind
        remote_run(["mkdir", "-p", target])
        config["files"].append({"source": str(local), "target": target})
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, indent=2))

    def stage(action, route=False):
        start = time.monotonic()
        output = run(
            [
                sys.executable,
                str(ROOT / "cutover.py"),
                action,
                "--config",
                str(config_path),
                "--evidence",
                str(root / "move"),
                "--execute",
            ]
            + (["--routes-confirmed"] if route else [])
        )
        (root / (action + ".jsonl")).write_bytes(output)
        print(
            json.dumps({"stage": action, "seconds": round(time.monotonic() - start, 3)}), flush=True
        )

    stage("presync")
    # A file and accepted in-flight job arrive after presync, before freeze.
    (root / "source-files/spool/final-intake.txt").write_text("fictional intake after presync\n")
    run(hook("source", "job"))
    stage("freeze-and-move")
    stage("switch", True)
    run(hook("target", "write"))
    remote_run(
        ["tee", remote + "/files/recordings/aws-window.txt"],
        b"fictional recording accepted on AWS\n",
    )
    stage("rollback")
    stage("resume-source", True)
    result = sql(
        source_db,
        b"SELECT count(*) FROM cutover_writes; SELECT count(*) FROM cutover_writes WHERE note='fictional AWS window write';",  # noqa: E501 -- literal SQL or fixed remote shell script
    )
    if (
        result.decode().splitlines() != ["10002", "1"]
        or not (root / "source-files/recordings/aws-window.txt").is_file()
    ):
        raise RuntimeError("rollback lost acknowledged AWS window write")
    (root / "result.json").write_text(
        json.dumps(
            {
                "passed": True,
                "remote_root": remote,
                "source_database": source_db,
                "target_database": target_db,
                "rows_after_rollback": 10002,
                "aws_window_row_preserved": True,
                "aws_window_file_preserved": True,
                "shared_stack_restarted": False,
                "public_dns_changed": False,
            },
            indent=2,
        )
    )
    # Stop only our own private fixture processes; keep DB/files as evidence.
    for port in ports:
        remote_run(["sh", "-c", f'kill "$(cat {remote}/service-{port}.pid)"'])
    print("fictional round trip passed; retained private evidence")


if __name__ == "__main__":
    main()

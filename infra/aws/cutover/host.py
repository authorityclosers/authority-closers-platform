#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""Host lifecycle adapter; uses a reviewed JSON profile, never loads Docker envs.

Profile lists immutable Caddy route selectors, full writer inventory and containers.
The freeze route must return 503 for ALL production paths, including intake.
Default is inspection only. Execute only via the approved operator runbook.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path


def run(argv):
    r = subprocess.run(argv, capture_output=True, check=False, timeout=1000)
    if r.returncode:
        raise RuntimeError("host command failed")
    return r.stdout.decode().strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument(
        "action",
        choices=["hold", "drain", "fence", "start-held", "open", "assert-held", "backups-ready"],
    )
    args = p.parse_args()
    raw = Path(args.profile).read_bytes()
    c = json.loads(raw)
    if not args.execute:
        print(
            json.dumps(
                {
                    "action": args.action,
                    "profile_sha256": hashlib.sha256(raw).hexdigest(),
                    "execute": False,
                }
            )
        )
        return
    if not c.get("inventory_review_record"):
        raise RuntimeError("writer/mount inventory review required")
    writers = c["writers"]
    if not writers or set(c["drain"]) - set(writers) or set(c["held_services"]) & set(writers):
        raise RuntimeError("incomplete writer inventory")

    # Service/timer names come from reviewed profile, never broad stop globs.
    def disable_restarts():
        for name in writers:
            expected = c["restart_policies"][name]
            current = run(
                ["docker", "inspect", "--format", "{{.HostConfig.RestartPolicy.Name}}", name]
            )
            if current not in {expected, "no"}:
                raise RuntimeError("restart policy differs from reviewed inventory")
            run(["docker", "update", "--restart=no", name])

    def stopped():
        for name in writers:
            if run(["docker", "inspect", "--format", "{{.State.Running}}", name]) != "false":
                raise RuntimeError("writer remains running")
        for unit in c["writer_units"]:
            if run(["systemctl", "show", "-p", "ActiveState", "--value", unit]) not in {
                "inactive",
                "failed",
            }:
                raise RuntimeError("host writer unit still active")

    def select(route):
        path, selector = Path(c[route]), Path(c["route_selector"])
        if not path.is_file() or path.is_symlink() or not selector.is_symlink():
            raise RuntimeError("reviewed route and existing selector required")
        # Candidate validation uses the complete reviewed Caddy configuration.
        temp = selector.with_name(".cutover-" + uuid.uuid4().hex)
        temp.symlink_to(path)
        temp.replace(selector)
        run(c["caddy_validate"])
        run(c["caddy_reload"])
        if selector.resolve() != path.resolve():
            raise RuntimeError("route selector changed concurrently")

    if args.action == "hold":
        text = Path(c["freeze_route"]).read_text()
        if "reverse_proxy" in text or "503" not in text:
            raise RuntimeError("freeze route must fence intake as well as API")
        select("freeze_route")
        run(c["held_probe"])
    elif args.action == "drain":
        disable_restarts()
        for unit in c["writer_units"]:
            run(["systemctl", "stop", unit])
        # SIGTERM, wait, inspect. Never docker stop's automatic timeout SIGKILL.
        for name in c["drain"]:
            if run(["docker", "inspect", "--format", "{{.State.Running}}", name]) == "true":
                run(["docker", "kill", "--signal=TERM", name])
        deadline = time.monotonic() + c.get("drain_seconds", 960)
        for name in c["drain"]:
            while run(["docker", "inspect", "--format", "{{.State.Running}}", name]) == "true":
                if time.monotonic() > deadline:
                    raise RuntimeError("drain deadline exceeded; do not kill active jobs")
                time.sleep(1)
            if run(["docker", "inspect", "--format", "{{.State.ExitCode}}", name]) != "0":
                raise RuntimeError("worker did not exit cleanly")
    elif args.action == "fence":
        disable_restarts()
        for name in writers:
            if run(["docker", "inspect", "--format", "{{.State.Running}}", name]) == "true":
                # Remaining API/intake connections must finish before dump.
                run(["docker", "kill", "--signal=TERM", name])
        deadline = time.monotonic() + c.get("connection_drain_seconds", 960)
        for name in writers:
            while run(["docker", "inspect", "--format", "{{.State.Running}}", name]) == "true":
                if time.monotonic() > deadline:
                    raise RuntimeError("connection drain exceeded; origin remains held")
                time.sleep(1)
            if run(["docker", "inspect", "--format", "{{.State.ExitCode}}", name]) != "0":
                raise RuntimeError("writer exit was unclean")
        stopped()
        # Must check active transactions, integration/native imports and leases
        # using an operator-reviewed query/probe, no inferred status vocabulary.
        run(c["fence_probe"])
    elif args.action == "start-held":
        run(c["held_probe"])
        stopped()
        # Only frontend/API containers; background consumers wait for open.
        for name in c["held_services"]:
            run(["docker", "start", name])
        run(c["private_ready_probe"])
    elif args.action == "open":
        run(c["backup_ready_probe"])
        run(c["private_ready_probe"])
        for name in writers:
            run(["docker", "update", "--restart=" + c["restart_policies"][name], name])
        for name in c["open_services"]:
            run(["docker", "start", name])
        run(c["opened_ready_probe"])
        for unit in c["writer_units"]:
            run(["systemctl", "start", unit])
        select("live_route")
    elif args.action == "backups-ready":
        run(c["backup_ready_probe"])
    else:
        run(c["held_probe"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("host adapter refused; preserve hold and inspect privately", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Numeric host/cgroup evidence, scoped to ac-rehearsal; no env or logs exported."""

import json
import subprocess
import time
from pathlib import Path


def command(*args):
    return subprocess.check_output(args, text=True).strip()  # noqa: S603 - fixed docker commands


def pairs(path):
    return {
        line.split()[0].rstrip(":"): int(line.split()[1])
        for line in Path(path).read_text().splitlines()
        if len(line.split()) > 1
    }


def sample():
    result = {
        "epoch": time.time(),
        "mem_kib": pairs("/proc/meminfo"),
        "cpu": [int(n) for n in Path("/proc/stat").read_text().splitlines()[0].split()[1:]],
        "load": Path("/proc/loadavg").read_text().split()[:3],
        "containers": [],
    }
    ids = command(
        "docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=ac-rehearsal"
    ).split()
    if not ids:
        return result
    for obj in json.loads(command("docker", "inspect", *ids)):
        pid = obj["State"]["Pid"]
        item = dict(
            name=obj["Name"].lstrip("/"),
            state=obj["State"]["Status"],
            oom=obj["State"]["OOMKilled"],
            restarts=obj["RestartCount"],
            cap=obj["HostConfig"]["Memory"],
            started=obj["State"]["StartedAt"],
        )
        if pid:
            try:
                relative = Path(f"/proc/{pid}/cgroup").read_text().strip().split("::")[-1]
                group = Path("/sys/fs/cgroup") / relative.lstrip("/")
                for name in ("memory.current", "memory.peak", "memory.swap.current"):
                    item[name] = int((group / name).read_text())
                item["memory.events"] = pairs(group / "memory.events")
                item["cpu.stat"] = pairs(group / "cpu.stat")
                rss = 0
                for process in (group / "cgroup.procs").read_text().split():
                    try:
                        for line in Path(f"/proc/{process}/status").read_text().splitlines():
                            if line.startswith("VmRSS:"):
                                rss += int(line.split()[1])
                    except FileNotFoundError:
                        pass
                item["rss_kib"] = rss
            except FileNotFoundError:
                item["race"] = True
        result["containers"].append(item)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=0)
    args = parser.parse_args()
    deadline = time.monotonic() + args.seconds
    while True:
        print(json.dumps(sample()), flush=True)
        if time.monotonic() >= deadline:
            break
        time.sleep(10)

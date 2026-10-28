#!/usr/bin/env python3
"""Summarize numeric rehearsal samples; never requires runtime credentials."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def analyse(samples):
    if len(samples) < 2:
        raise ValueError("At least two samples required")
    groups = defaultdict(list)
    for sample in samples:
        for container in sample["containers"]:
            groups[container["name"]].append(container)
    containers = {}
    for name, rows in groups.items():
        first, last = rows[0], rows[-1]
        containers[name] = {
            "cap_mib": last["cap"] / 2**20,
            "sampled_peak_mib": max(row.get("memory.current", 0) for row in rows) / 2**20,
            "lifetime_peak_mib": max(row.get("memory.peak", 0) for row in rows) / 2**20,
            "rss_peak_mib": max(row.get("rss_kib", 0) for row in rows) / 1024,
            "swap_peak_mib": max(row.get("memory.swap.current", 0) for row in rows) / 2**20,
            "restart_delta": last["restarts"] - first["restarts"],
            "oom_kill_delta": last.get("memory.events", {}).get("oom_kill", 0)
            - first.get("memory.events", {}).get("oom_kill", 0),
            "all_samples_running": all(row["state"] == "running" for row in rows),
            "within_cap": all(row.get("memory.current", 0) <= row["cap"] for row in rows),
        }
    cpu, steal = [], []
    for first, last in zip(samples, samples[1:], strict=False):
        delta = [b - a for a, b in zip(first["cpu"], last["cpu"], strict=False)]
        total = sum(delta[:8])
        if total > 0:
            cpu.append(100 * sum(delta[i] for i in (0, 1, 2, 5, 6)) / total)
            steal.append(100 * delta[7] / total)
    first, last = samples[0], samples[-1]
    delta = [b - a for a, b in zip(first["cpu"], last["cpu"], strict=False)]
    mean_cpu = 100 * sum(delta[i] for i in (0, 1, 2, 5, 6)) / sum(delta[:8])
    duration = last["epoch"] - first["epoch"]
    return {
        "start_epoch": first["epoch"],
        "end_epoch": last["epoch"],
        "sampled_seconds": duration,
        "samples": len(samples),
        "host_cpu_mean_percent": mean_cpu,
        "host_cpu_peak_interval_percent": max(cpu, default=0),
        "host_steal_mean_interval_percent": sum(steal) / max(1, len(steal)),
        "host_steal_peak_interval_percent": max(steal, default=0),
        "minimum_available_mib": min(row["mem_kib"]["MemAvailable"] / 1024 for row in samples),
        "maximum_host_swap_used_mib": max(
            (row["mem_kib"]["SwapTotal"] - row["mem_kib"]["SwapFree"]) / 1024 for row in samples
        ),
        "estimated_credit_net_consumption": (mean_cpu / 100 * 2 - 0.4) * duration / 60,
        "credit_balance": None,
        "credit_estimate_note": (
            "Estimate from guest CPU, 2 vCPU and 0.4-core baseline. "
            "Negative means net accrual. No CloudWatch balance or confirmed exhaustion."
        ),
        "containers": containers,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            analyse(
                [
                    json.loads(line)
                    for line in args.jsonl.read_text().splitlines()
                    if line.startswith("{")
                ]
            ),
            indent=2,
        )
    )

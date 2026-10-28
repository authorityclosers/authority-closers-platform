#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""Command-array cutover driver. Default invocation describes steps without executing."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from functools import partial
from pathlib import Path

FORWARD = [
    "hold_source",
    "drain_source",
    "fence_source",
    "dump",
    "restore",
    "delta",
    "verify",
    "start_target_held",
]
REVERSE = [
    "hold_target",
    "drain_target",
    "fence_target",
    "hold_source",
    "fence_source",
    "safety_dump",
    "reverse_dump",
    "reverse_restore",
    "reverse_delta",
    "reverse_verify",
    "start_source_held",
]


def command(argv, data=None, timeout=600):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("command failed; private diagnostics suppressed")
    return result.stdout


class Kit:
    def __init__(self, config, evidence):
        raw = Path(config).read_bytes()
        self.c = json.loads(raw)
        self.pin = hashlib.sha256(raw).hexdigest()
        self.root = Path(evidence).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.root / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if self.state and self.state["config_sha256"] != self.pin:
            raise RuntimeError("configuration differs from evidence pin")
        self.state["config_sha256"] = self.pin
        self.timeout = int(self.c.get("step_timeout", 600))

    def validate(self):
        if self.c.get("environment") not in {"fictional", "production"}:
            raise RuntimeError("only fictional or approved production configurations are supported")
        if self.c["environment"] == "production":
            if not self.c.get("inventory_review_record") or "REPLACE_" in json.dumps(self.c):
                raise RuntimeError("deployed writer/mount inventory and reviewed hooks required")
            if len(self.c.get("files", [])) < 3:
                raise RuntimeError("recordings, media and spool roots must be inventoried")
            required = set(FORWARD + REVERSE) - {
                "dump",
                "restore",
                "delta",
                "verify",
                "safety_dump",
                "reverse_dump",
                "reverse_restore",
                "reverse_delta",
                "reverse_verify",
            }
            required |= {
                "open_source",
                "open_target",
                "source_held_canary",
                "target_held_canary",
                "source_canary",
                "target_canary",
            }
            for name in required:
                if (
                    not isinstance(self.c.get("hooks", {}).get(name), list)
                    or not self.c["hooks"][name]
                ):
                    raise RuntimeError("all reviewed lifecycle hooks required")

    def save(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2) + "\n")
        tmp.replace(self.state_path)

    def hook(self, name):
        argv = self.c["hooks"].get(name)
        if not argv or not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
            raise RuntimeError("missing command-array hook: " + name)
        return command(argv, timeout=self.timeout)

    def db(self, side, action, data=None):
        return command(self.c[side]["database"] + [action], data, self.timeout)

    def manifest(self, side, index):
        return command(
            self.c[side]["manifest"] + [self.c["files"][index][side]], timeout=self.timeout
        )

    def sync(self, reverse=False):
        sides = ("target", "source") if reverse else ("source", "target")
        if all(self.c[s].get("host") for s in sides):
            raise RuntimeError("run rsync driver on one origin")
        for index, paths in enumerate(self.c["files"]):
            ends = []
            for side in sides:
                host, path = self.c[side].get("host", ""), paths[side]
                if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or path == "/":
                    raise RuntimeError("file root must be absolute and specific")
                if host and (host.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.@-]+", host)):
                    raise RuntimeError("unsafe SSH host")
                ends.append((host + ":" if host else "") + path.rstrip("/") + "/")
            stats = command(
                [
                    "nice",
                    "-n",
                    "19",
                    "ionice",
                    "-c",
                    "3",
                    "rsync",
                    "-aH",
                    "--numeric-ids",
                    "--stats",
                    "--partial",
                    "--partial-dir=.cutover-partial",
                    "--protect-args",
                    "--bwlimit=" + str(self.c.get("bwlimit_kib", 4096)),
                    *(["--rsync-path", self.c["rsync_path"]] if self.c.get("rsync_path") else []),
                    "-e",
                    self.c.get("rsync_ssh", "ssh -o BatchMode=yes"),
                    *ends,
                ],
                timeout=self.timeout,
            )
            with (self.root / "rsync-statistics.jsonl").open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "direction": "reverse" if reverse else "forward",
                            "root_index": index,
                            "statistics": stats.decode(errors="replace"),
                        }
                    )
                    + "\n"
                )

    def verify(self, reverse=False):
        sides = ("target", "source") if reverse else ("source", "target")
        counts = [json.loads(self.db(s, "counts")) for s in sides]
        if counts[0] != counts[1] or not counts[0].get("tables"):
            raise RuntimeError("table/sequence/schema inventory mismatch")
        summary = {"tables": len(counts[0]["tables"]), "files": []}
        for i in range(len(self.c["files"])):
            manifests = [json.loads(self.manifest(s, i)) for s in sides]
            if manifests[0] != manifests[1]:
                raise RuntimeError("durable file hash/metadata inventory mismatch")
            summary["files"].append(
                {"count": len(manifests[0]), "bytes": sum(v[0] for v in manifests[0].values())}
            )
        (self.root / ("reverse-verification.json" if reverse else "verification.json")).write_text(
            json.dumps(summary, indent=2)
        )

    def step(self, name, fn):
        start, status = time.monotonic(), "failed"
        try:
            fn()
            status = "ok"
        finally:
            receipt = {
                "step": name,
                "status": status,
                "seconds": round(time.monotonic() - start, 3),
            }
            with (self.root / "timings.jsonl").open("a") as f:
                f.write(json.dumps(receipt) + "\n")
            print(json.dumps(receipt), flush=True)
            self.state["last_step"] = receipt
            self.save()

    def move(self, reverse=False):
        allowed = (
            {"target-held", "target-live", "target-opening", "switch-failed"}
            if reverse
            else {"presynced"}
        )
        if self.state.get("phase") not in allowed:
            raise RuntimeError("incorrect move phase")
        started = time.monotonic()
        self.state["phase"] = "moving-reverse" if reverse else "moving-forward"
        self.state["freeze_started_utc"] = time.time()
        self.save()
        for name in REVERSE if reverse else FORWARD:
            if name in {"dump", "reverse_dump", "safety_dump"}:
                side = "target" if name == "reverse_dump" else "source"

                def work(side=side, name=name):
                    data = self.db(side, "dump")
                    if not data.startswith(b"PGDMP"):
                        raise RuntimeError("invalid custom dump")
                    (self.root / (name + ".dump")).write_bytes(data)
                    self.state.setdefault("dump_receipts", {})[name] = {
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
            elif name in {"restore", "reverse_restore"}:
                side = "source" if reverse else "target"
                dump = self.root / ("reverse_dump.dump" if reverse else "dump.dump")

                def work(side=side, dump=dump):
                    self.db(side, "restore", dump.read_bytes())
            elif name in {"delta", "reverse_delta"}:
                work = partial(self.sync, reverse)
            elif name in {"verify", "reverse_verify"}:
                work = partial(self.verify, reverse)
            else:
                work = partial(self.hook, name)
            self.step(name, work)
            if not reverse and time.monotonic() - started > int(
                self.c.get("freeze_budget_seconds", 600)
            ):
                raise RuntimeError("freeze budget exceeded; keep both origins held")
        self.state["phase"] = "source-held" if reverse else "target-held"
        self.state["reverse_seconds" if reverse else "forward_seconds"] = round(
            time.monotonic() - started, 3
        )
        self.save()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=[
            "presync",
            "freeze-and-move",
            "switch",
            "rollback",
            "resume-source",
            "abort-before-open",
        ],
    )
    p.add_argument("--config", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--approval-record")
    p.add_argument("--routes-confirmed", action="store_true")
    args = p.parse_args()
    os.umask(0o077)
    kit = Kit(args.config, args.evidence)
    if not args.execute:
        print(
            json.dumps(
                {
                    "action": args.action,
                    "execution": False,
                    "config_sha256": kit.pin,
                    "steps": FORWARD
                    if args.action == "freeze-and-move"
                    else REVERSE
                    if args.action == "rollback"
                    else [args.action],
                    "routing": "owner only: ac-kvm4-prod <-> ac-aws-prod",
                }
            )
        )
        return
    if kit.c.get("environment") != "fictional":
        approval = json.loads(Path(args.approval_record or "/nonexistent").read_text())
        if (
            approval.get("config_sha256") != kit.pin
            or approval.get("action") != args.action
            or not approval.get("owner_record")
        ):
            raise RuntimeError("exact owner data-change approval required")
    kit.validate()
    approved_pin = kit.pin
    with (kit.root / "operation.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Re-read under the lock, avoiding a stale pre-lock phase/config view.
        kit = Kit(args.config, args.evidence)
        if kit.pin != approved_pin:
            raise RuntimeError("configuration changed after approval validation")
        kit.validate()
        if args.action == "presync":
            if kit.state.get("phase") not in {None, "presynced"}:
                raise RuntimeError("active move cannot be presynced")
            kit.step("presync", kit.sync)
            sizes = [json.loads(kit.manifest("source", i)) for i in range(len(kit.c["files"]))]
            kit.state.update(
                presync_files=sum(len(m) for m in sizes),
                presync_bytes=sum(v[0] for m in sizes for v in m.values()),
                phase="presynced",
            )
        elif args.action == "abort-before-open":
            if kit.state.get("phase") not in {"moving-forward", "target-held"}:
                raise RuntimeError("abort is only safe before target writes")
            for name in ["hold_target", "drain_target", "fence_target", "start_source_held"]:
                kit.step(name, partial(kit.hook, name))
            kit.state["phase"] = "source-held"
        elif args.action in {"freeze-and-move", "rollback"}:
            kit.move(args.action == "rollback")
        else:
            source = args.action == "resume-source"
            if (
                kit.state.get("phase") != ("source-held" if source else "target-held")
                or not args.routes_confirmed
            ):
                raise RuntimeError("verified held origin and owner route confirmation required")
            side = "source" if source else "target"
            kit.step("held_canary", lambda: kit.hook(side + "_held_canary"))
            kit.state["phase"] = side + "-opening"
            kit.save()
            try:
                kit.step("open_" + side, lambda: kit.hook("open_" + side))
                kit.step("public_canary", lambda: kit.hook(side + "_canary"))
            except Exception:
                # Persist possible write exposure BEFORE attempting safety hooks.
                # Even a failed re-hold must never permit the pre-open abort path.
                kit.state["phase"] = "source-recovery" if source else "switch-failed"
                kit.save()
                for action in ("hold_", "drain_", "fence_"):
                    # step() records failures; still attempt all safety hooks.
                    with suppress(Exception):
                        kit.step(action + side, partial(kit.hook, action + side))
                raise
            kit.state["phase"] = side + "-live"
            kit.state[side + "_write_freeze_seconds"] = round(
                time.time() - kit.state.get("freeze_started_utc", time.time()), 3
            )
        kit.save()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("cutover refused/failed; inspect receipts; keep origins held", file=sys.stderr)
        sys.exit(1)

"""File the lab's misses through the app's own Report a problem, as a sandbox seller.

    file_bugs.py <tenant_id> <seller> <bugs.json> [--send]

bugs.json is a list of {"id", "title", "expected", "actual", "builder", "route",
"severity", "blocks_work"}. Dry run unless --send: it prints what it would file. Each
report's words carry the scenario id, expected and actual, and the builder the miss is for
(call analysis/report, Leads, Home, capture-setup), so the board routes it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path

_spec = importlib.util.spec_from_file_location("sim_inject", Path(__file__).with_name("inject.py"))
assert _spec and _spec.loader
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)

NS = uuid.UUID("3d1f8e2a-9c4b-4a7d-b2e6-5f0a1c9d8e73")


def words(bug: dict[str, str]) -> str:
    return (
        f"[SIM {bug['id']}] [{bug.get('severity', 'medium').upper()}] {bug['title']}\n"
        f"Expected: {bug['expected']}\n"
        f"Actual: {bug['actual']}\n"
        f"Builder: {bug['builder']}\n"
        "Found by the simulation lab (scripts/simulation, synthetic fictional call/event, "
        "sandbox organisation on dev)."
    )[:4000]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id")
    parser.add_argument("seller")
    parser.add_argument("bugs")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    bugs = json.loads(Path(args.bugs).read_text(encoding="utf-8"))
    if not args.send:
        for bug in bugs:
            print(words(bug), "\n---")
        return
    http_ = inject.Http("http://127.0.0.1:8101", inject.DEV_HOST)
    inject.sign_in(http_, args.seller, args.tenant_id)
    try:
        for bug in bugs:
            body = {
                "command_id": str(uuid.uuid5(NS, f"{bug['id']}:{bug['title']}")),
                "words": words(bug),
                "blocks_work": bool(bug.get("blocks_work")),
                "route": bug.get("route") or "/calls",
                "area": bug.get("area"),
                "context": {
                    "source": "simulation-lab",
                    "scenario": bug["id"],
                    "builder": bug["builder"],
                },
            }
            try:
                status, answer = http_.call("POST", "/v1/bug-reports", body, ok=(200, 201, 202))
                print(bug["id"], status, (answer or {}).get("id") or (answer or {}).get("bug_id"))
            except inject.Refused as error:
                print(bug["id"], "refused", error.status)
    finally:
        http_.call("POST", "/v1/auth/logout", ok=(200, 204, 401))


if __name__ == "__main__":
    sys.exit(main())

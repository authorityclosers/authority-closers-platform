"""What the seller's screens show after the lab's calls: Home (my day), Performance, the call
reports and each call's lead page. Read-only.

    screens.py <tenant_id> <alias> <results-dir> [--day YYYY-MM-DD]

``--day`` is the India date the fake phone dated the calls (the last working day). Writes
``<results>/screens.json`` and prints a summary. Passwords come from the environment, as for
inject.py.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location("sim_inject", Path(__file__).with_name("inject.py"))
assert _spec and _spec.loader
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)


def read(http_: Any, path: str) -> Any:
    try:
        return http_.call("GET", path, ok=(200,))[1]
    except inject.Refused as error:
        return {"_refused": error.status}


def lead_page(run: dict[str, Any]) -> dict[str, Any] | None:
    """Does the call show once on its lead, with its recording and what the AI read?"""
    detail = run.get("lead")
    event_id = str((run.get("recording_call") or {}).get("event_id") or "")
    if not isinstance(detail, dict) or not event_id:
        return None
    events = detail.get("events") or []
    text = json.dumps(events, ensure_ascii=False)
    mine = [e for e in events if event_id in json.dumps(e)]
    return {
        "events_with_this_call": len(mine),
        "kinds": sorted({str(e.get("kind") or e.get("type")) for e in mine}),
        "submission_on_lead": str(run.get("submission_id")) in text,
        "events_total": len(events),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant")
    parser.add_argument("alias")
    parser.add_argument("results")
    parser.add_argument("--day", default="2026-10-31")
    args = parser.parse_args()
    results = Path(args.results)
    http_ = inject.Http("http://127.0.0.1:8101", inject.DEV_HOST)
    out: dict[str, Any] = {"seller": args.alias, "day": args.day}
    try:
        inject.sign_in(http_, args.alias, args.tenant)
        out["my_day"] = read(http_, "/v1/lead-desk/my-day")
        out["performance_today"] = read(http_, "/v1/lead-desk/performance/sellers?days=1")
        out["performance_7d"] = read(http_, "/v1/lead-desk/performance/sellers?days=7")
        out["owner_performance_7d"] = read(http_, "/v1/lead-desk/reports/performance?days=7")
        out["call_report_day"] = read(
            http_, f"/v1/lead-desk/reports/calls?start={args.day}&end={args.day}"
        )
        # The Calls tab: the seller's own submissions, and its summary line.
        out["calls_list"] = read(http_, "/v1/conversation/acquisition/submissions")
        out["calls_summary"] = read(http_, "/v1/conversation/acquisition/submissions/summary")
    finally:
        with contextlib.suppress(Exception):  # the session ends with the process
            http_.call("POST", "/v1/auth/logout", ok=(200, 204, 401))
    pages = {}
    for file in sorted(results.glob("S*.json")):
        run = json.loads(file.read_text(encoding="utf-8"))
        if run.get("id"):
            pages[run["id"]] = lead_page(run)
    out["lead_pages"] = pages
    (results / "screens.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for key in ("my_day", "performance_today", "performance_7d", "owner_performance_7d"):
        print(key, json.dumps(out.get(key), ensure_ascii=False)[:600])
    print("call_report_day", json.dumps(out.get("call_report_day"), ensure_ascii=False)[:400])
    calls = out.get("calls_list")
    rows = (
        calls.get("submissions") or calls.get("items") or calls.get("calls")
        if isinstance(calls, dict)
        else calls
    )
    print("calls_list", len(rows) if isinstance(rows, list) else json.dumps(calls)[:200])
    print("calls_summary", json.dumps(out.get("calls_summary"), ensure_ascii=False)[:400])
    for scenario, page in pages.items():
        print(scenario, json.dumps(page))


if __name__ == "__main__":
    main()

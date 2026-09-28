#!/usr/bin/env python3
"""Print weekly event-derived Paperclip agent metrics as Markdown."""

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

FAILED = {"failed", "cancelled", "timed_out"}
CORE_COLUMNS = (
    "Agent|Tasks done|Cycle median|Cycle p90|Bounces|Tokens / done task|Runs / done task|Failed-run %"
).split("|")
GITHUB_COLUMNS = "First-try CI|Owner changes|Post-merge bugs|Scope|Evidence|Gate".split("|")


def fetch_json(path, method="GET"):
    """Only network entry point; this report permits GET requests only."""
    if method != "GET":
        raise ValueError("agent scorecard permits GET requests only")
    request = urllib.request.Request(
        os.environ["PAPERCLIP_API_URL"].rstrip("/") + path,
        headers={"Authorization": "Bearer " + os.environ["PAPERCLIP_API_KEY"]},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Paperclip read failed") from exc


def fetch_report_data(company_id):
    issues = fetch_json(f"/api/companies/{company_id}/issues")
    agents = fetch_json(f"/api/companies/{company_id}/agents")
    runs = fetch_json(f"/api/companies/{company_id}/heartbeat-runs")
    activity = {
        i["id"]: fetch_json(f"/api/issues/{i['id']}/activity") for i in issues if i.get("id")
    }
    return {"issues": issues, "agents": agents, "runs": runs, "activity": activity}


def week_window(value=None, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    monday = (
        dt.date.fromisoformat(value) if value else today - dt.timedelta(days=today.weekday() + 7)
    )
    if monday.weekday():
        raise ValueError("--week must be a Monday (UTC)")
    start = dt.datetime.combine(monday, dt.time(), dt.timezone.utc)
    return monday, start.timestamp(), (start + dt.timedelta(days=7)).timestamp()


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def run_tokens(run):
    try:
        raw = run["usageJson"]
        usage = json.loads(raw) if isinstance(raw, str) else raw
        values = [usage[key] for key in ("inputTokens", "outputTokens")]
        return (
            sum(values)
            if isinstance(usage, dict) and all(isinstance(v, (int, float)) for v in values)
            else None
        )
    except (KeyError, TypeError, ValueError):
        return None


def build_report(data, monday, start, end):
    issues = {item["id"]: item for item in data["issues"] if item.get("id")}
    names = {
        a["id"]: a.get("name") or a.get("displayName") or a["id"]
        for a in data["agents"]
        if a.get("id")
    }
    for run in data["runs"]:
        if run.get("agentId") and run["agentId"] not in names:
            names[run["agentId"]] = run.get("agentName") or run["agentId"]

    done_by = defaultdict(set)
    bounces = Counter()
    cycles = defaultdict(list)
    for issue_id, events in data["activity"].items():
        owner = issues.get(issue_id, {}).get("assigneeAgentId")
        starts, completions = [], []
        for event in events:
            when = timestamp(event.get("createdAt"))
            status = ((event.get("details") or {}).get("changes") or {}).get("status") or {}
            before, after = status.get("from"), status.get("to")
            if when is not None and start <= when < end:
                bounces[owner] += before == "in_review" and after == "in_progress"
                if after == "done":
                    completions.append(when)
            if after == "in_progress" and when is not None:
                starts.append(when)
        if completions:
            done_by[owner].add(issue_id)
            end_at = max(completions)
            start_at = min((t for t in starts if t <= end_at), default=None)
            if start_at is not None:
                cycles[owner].append((end_at - start_at) / 86400)
    relevant = {issue_id for task_ids in done_by.values() for issue_id in task_ids}
    by_issue = defaultdict(list)
    week_runs = []
    for run in data["runs"]:
        run_at = timestamp(run.get("startedAt") or run.get("createdAt"))
        if run_at is not None and start <= run_at < end:
            week_runs.append(run)
        issue_id = (run.get("contextSnapshot") or {}).get("issueId")
        if issue_id in relevant:
            by_issue[issue_id].append(run)

    groups = set(names) | set(done_by) | set(bounces)
    groups.update(run["agentId"] for run in week_runs if run.get("agentId"))
    company_key = "__company__"

    def metrics(group):
        selected = relevant if group == company_key else done_by.get(group, set())
        duration_sets = cycles.values() if group == company_key else [cycles.get(group, [])]
        values = [v for durations in duration_sets for v in durations]
        cycle_missing = len(values) < len(selected)
        median = statistics.median(values) if values and not cycle_missing else None
        p90 = sorted(values)[int(0.9 * len(values) - 0.1)] if values and not cycle_missing else None
        selected_runs = [r for r in week_runs if group == company_key or r.get("agentId") == group]
        failed = sum(r.get("status") in FAILED for r in selected_runs)
        failed_pct = 100 * failed / len(selected_runs) if selected_runs else None
        task_runs = [r for issue_id in selected for r in by_issue.get(issue_id, [])]
        complete_runs = bool(selected) and all(by_issue.get(issue_id) for issue_id in selected)
        token_values = [run_tokens(run) for run in task_runs]
        tokens = (
            sum(token_values) / len(selected)
            if complete_runs and all(v is not None for v in token_values)
            else None
        )
        runs_per_task = len(task_runs) / len(selected) if complete_runs else None
        return {
            "done": len(selected),
            "median": median,
            "p90": p90,
            "cycle_missing": cycle_missing,
            "bounces": sum(bounces.values()) if group == company_key else bounces[group],
            "tokens": tokens,
            "runs_per_task": runs_per_task,
            "failed_pct": failed_pct,
        }

    rows = [
        (names.get(group, "Unassigned"), metrics(group))
        for group in sorted(groups, key=lambda g: str(names.get(g, "Unassigned")).lower())
    ]
    company = metrics(company_key)
    rows.append(("Company", company))
    failures = []
    for run in week_runs:
        if run.get("status") in FAILED:
            issue_id = (run.get("contextSnapshot") or {}).get("issueId")
            failures.append(
                (
                    names.get(run.get("agentId"), run.get("agentName") or "Unassigned"),
                    issues.get(issue_id, {}).get("identifier") or issue_id or "n/a",
                    run.get("status"),
                )
            )
    alerts = []
    for label, row in rows:
        if row["failed_pct"] is not None and row["failed_pct"] > 10:
            alerts.append(f"{label}: failed runs {row['failed_pct']:.1f}% (>10%)")
        if row["p90"] is not None and row["p90"] > 3:
            alerts.append(f"{label}: cycle-time p90 {row['p90']:.2f}d (>3d)")
    return {"week": monday, "rows": rows, "failures": failures, "alerts": alerts}


def render_report(report):
    headers = CORE_COLUMNS + GITHUB_COLUMNS
    output = [
        f"# Weekly agent scorecard: {report['week'].isoformat()} UTC",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for label, row in report["rows"]:
        no_cycles = "n/a (no done tasks)" if not row["done"] else "n/a (missing activity)"
        cells = [
            label,
            str(row["done"]),
            f"{row['median']:.2f}d" if row["median"] is not None else no_cycles,
            f"{row['p90']:.2f}d" if row["p90"] is not None else no_cycles,
            str(row["bounces"]),
            f"{row['tokens']:.2f}" if row["tokens"] is not None else "n/a (missing usage)",
            f"{row['runs_per_task']:.2f}"
            if row["runs_per_task"] is not None
            else "n/a (missing runs)",
            f"{row['failed_pct']:.1f}%" if row["failed_pct"] is not None else "n/a (no runs)",
        ] + ["n/a (AUT-57)" for _ in GITHUB_COLUMNS]
        output.append("| " + " | ".join(str(v).replace("|", "\\|") for v in cells) + " |")
    output += ["", "## Alerts", ""] + [f"- {a}" for a in report["alerts"] or ["None"]]
    output += ["", "## Failures", "", "| Agent | Issue | Status |", "| --- | --- | --- |"]
    output += [f"| {a} | {i} | {s} |" for a, i, s in report["failures"] or [("None", "n/a", "n/a")]]
    return "\n".join(output) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="UTC Monday date (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    required = ("PAPERCLIP_API_URL", "PAPERCLIP_API_KEY", "PAPERCLIP_COMPANY_ID")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        print("Missing required environment variable(s): " + ", ".join(missing), file=sys.stderr)
        return 2
    try:
        monday, start, end = week_window(args.week)
        data = fetch_report_data(os.environ["PAPERCLIP_COMPANY_ID"])
        print(render_report(build_report(data, monday, start, end)), end="")
    except (ValueError, RuntimeError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "Paperclip read failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

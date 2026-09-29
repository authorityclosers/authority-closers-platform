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
ISSUE_PAGE_SIZE = 1000
CORE_COLUMNS = ["Agent", "Tasks done", "Cycle median", "Cycle p90",
                "Bounces", "Tokens / done task", "Runs / done task", "Failed-run %"]  # fmt: skip
GITHUB_COLUMNS = ["First-try CI", "Owner changes", "Post-merge bugs", "Scope", "Evidence", "Gate"]


def fetch_json(path, method="GET"):
    if method != "GET":
        raise ValueError("agent scorecard permits GET requests only")
    base_url = os.environ["PAPERCLIP_API_URL"].rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("PAPERCLIP_API_URL must use HTTP(S)")
    request = urllib.request.Request(  # noqa: S310 - scheme restricted above
        base_url + path,
        headers={"Authorization": "Bearer " + os.environ["PAPERCLIP_API_KEY"]},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - HTTP(S) only
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Paperclip read failed") from exc


def fetch_report_data(company_id, start):
    issues, offset = [], 0
    while True:
        page = fetch_json(
            f"/api/companies/{company_id}/issues?limit={ISSUE_PAGE_SIZE}&offset={offset}"
        )
        issues.extend(page)
        if len(page) < ISSUE_PAGE_SIZE:
            break
        offset += ISSUE_PAGE_SIZE
    agents = fetch_json(f"/api/companies/{company_id}/agents")
    runs = fetch_json(f"/api/companies/{company_id}/heartbeat-runs")
    activity = {
        issue["id"]: fetch_json(f"/api/issues/{issue['id']}/activity")
        for issue in issues
        if issue.get("id")
        and (updated := timestamp(issue.get("updatedAt"))) is not None
        and updated >= start
    }
    return {"issues": issues, "agents": agents, "runs": runs, "activity": activity}


def week_window(value=None, today=None):
    today = today or dt.datetime.now(dt.UTC).date()
    monday = (
        dt.date.fromisoformat(value) if value else today - dt.timedelta(days=today.weekday() + 7)
    )
    if monday.weekday():
        raise ValueError("--week must be a Monday (UTC)")
    start = dt.datetime.combine(monday, dt.time(), dt.UTC)
    return monday, start.timestamp(), (start + dt.timedelta(days=7)).timestamp()


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def run_tokens(run):
    try:
        usage = run["usageJson"]
        usage = json.loads(usage) if isinstance(usage, str) else usage
        values = [usage[key] for key in ("inputTokens", "outputTokens")]
        return (
            sum(values)
            if isinstance(usage, dict) and all(isinstance(v, (int, float)) for v in values)
            else None
        )
    except (KeyError, TypeError, ValueError):
        return None


def activity_status(event):
    details = event.get("details") or {}
    status = (details.get("changes") or {}).get("status") or {}
    before = status.get("from") or (details.get("_previous") or {}).get("status")
    after = status.get("to") or details.get("status")
    return before, after


def builder_for(issue, events):
    review_builder = done_builder = None
    for event in events:
        if event.get("actorType") != "agent" or not event.get("agentId"):
            continue
        before, after = activity_status(event)
        if before == "in_progress" and after == "in_review":
            review_builder = event["agentId"]
        elif after == "done" and before != "done":
            done_builder = event["agentId"]
    return review_builder or done_builder or issue.get("assigneeAgentId")


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
        issue = issues.get(issue_id, {})
        events = sorted(events, key=lambda e: timestamp(e.get("createdAt")) or 0)
        builder_events = events
        for index, event in enumerate(events):
            before, after = activity_status(event)
            if after == "done" and before != "done":
                builder_events = events[: index + 1]
                break
        owner = builder_for(issue, builder_events)
        starts = [t for t in [timestamp(issue.get("startedAt"))] if t is not None]
        completions, last_status = [], None
        for event in events:
            when = timestamp(event.get("createdAt"))
            details = event.get("details") or {}
            before, after = activity_status(event)
            started = (details.get("changes") or {}).get("startedAt") or {}
            starts.extend(filter(None, map(timestamp, (started.get("from"), started.get("to")))))
            checkout = event.get("type") == "issue.checked_out"
            # Paperclip records checkout/start metadata, not an in_progress status transition.
            if when is not None and (checkout or before == "in_progress"):
                starts.append(when)
            bounced = before == "in_review" and after == "in_progress"
            bounced |= last_status == "in_review" and (checkout or before == "in_progress")
            if when is not None and start <= when < end:
                bounces[owner] += bounced
                if after == "done":
                    completions.append(when)
            if after is not None:
                last_status = after
            elif checkout or last_status == "in_review" and before == "in_progress":
                last_status = "in_progress"
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
        median = statistics.median(values) if values else None
        p90 = sorted(values)[int(0.9 * len(values) - 0.1)] if values else None
        selected_runs = [r for r in week_runs if group == company_key or r.get("agentId") == group]
        failed = sum(r.get("status") in FAILED for r in selected_runs)
        failed_pct = 100 * failed / len(selected_runs) if selected_runs else None
        task_runs = [r for issue_id in selected for r in by_issue.get(issue_id, [])]
        complete_runs = bool(selected) and all(by_issue.get(issue_id) for issue_id in selected)
        token_values = [run_tokens(run) for run in task_runs]
        reported_tokens = [value for value in token_values if value is not None]
        tokens = sum(reported_tokens) / len(selected) if selected and reported_tokens else None
        runs_per_task = len(task_runs) / len(selected) if complete_runs else None
        return {
            "done": len(selected),
            "median": median,
            "p90": p90,
            "cycle_missing": len(selected) - len(values),
            "bounces": sum(bounces.values()) if group == company_key else bounces[group],
            "tokens": tokens,
            "unreported_runs": len(token_values) - len(reported_tokens),
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
        if row["cycle_missing"]:
            alerts.append(f"{label}: cycle time missing for {row['cycle_missing']} task(s)")
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
        tokens = row["tokens"]
        token_cell = (
            f"{tokens:.2f}"
            if tokens is not None
            else f"n/a ({'no usage' if row['done'] else 'no done tasks'})"
        )
        if tokens is not None and row["unreported_runs"]:
            token_cell += f" ({row['unreported_runs']} runs unreported)"
        cells = [
            label,
            str(row["done"]),
            f"{row['median']:.2f}d" if row["median"] is not None else no_cycles,
            f"{row['p90']:.2f}d" if row["p90"] is not None else no_cycles,
            str(row["bounces"]),
            token_cell,
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
        data = fetch_report_data(os.environ["PAPERCLIP_COMPANY_ID"], start)
        print(render_report(build_report(data, monday, start, end)), end="")
    except (ValueError, RuntimeError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "Paperclip read failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

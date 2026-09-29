#!/usr/bin/env python3
"""Print weekly event-derived Paperclip agent metrics as Markdown."""

import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from urllib.parse import urlparse

FAILED = {"failed", "cancelled", "timed_out"}
ISSUE_PAGE_SIZE = 1000
CORE_COLUMNS = ["Agent", "Tasks done", "Cycle median", "Cycle p90",
                "Bounces", "Tokens / done task", "Runs / done task", "Failed-run %"]  # fmt: skip
GITHUB_COLUMNS = ["PR cycle median", "PR cycle p90", "First-try CI", "Rework pushes",
                  "Owner changes", "Post-merge bugs", "Scope", "Evidence", "Gate"]  # fmt: skip
LANE_AGENTS = {
    "sales-xray": "Lead Engineer",
    "platform": "Platform Engineer",
    "admin": "Software Engineer",
    "devenv": "Dev Environment Lead",
}


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


def validate_gh_command(command):
    if command[:2] != ["gh", "api"]:
        raise ValueError("GitHub reads must use gh api")
    for i, arg in enumerate(command):
        if arg in ("-f", "-F", "--field", "--raw-field", "--input") or arg.startswith(
            ("-f", "-F", "--field=", "--raw-field=", "--input=")
        ):
            raise ValueError("agent scorecard permits read-only gh api calls")
        if arg in ("-X", "--method") and (i + 1 == len(command) or command[i + 1].upper() != "GET"):
            raise ValueError("agent scorecard permits GET requests only")
        if arg.startswith("--method=") and arg.partition("=")[2].upper() != "GET":
            raise ValueError("agent scorecard permits GET requests only")
        if arg.startswith("-X") and arg[2:].upper() != "GET":
            raise ValueError("agent scorecard permits GET requests only")


def gh_api(path, paginate=False):
    command = ["gh", "api", "--method", "GET"] + (["--paginate", "--slurp"] if paginate else []) + [path]
    validate_gh_command(command)
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    except OSError as exc:
        raise RuntimeError("GitHub read failed") from exc
    if result.returncode:
        raise RuntimeError("GitHub read failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub read failed") from exc


def gh_list(path, field=None):
    pages = gh_api(path, paginate=True)
    return [x for page in (pages if isinstance(pages, list) else [pages])
            for x in (page.get(field, []) if field else page)]


def github_repository():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        try:
            result = subprocess.run(["git", "remote", "get-url", "origin"],  # noqa: S607
                                    capture_output=True, text=True, check=False)
        except OSError as exc:
            raise RuntimeError("GitHub repository is unavailable") from exc
        remote = result.stdout.strip() if result.returncode == 0 else ""
        repo = remote.split(":", 1)[1] if remote.startswith("git@github.com:") else urlparse(remote).path.lstrip("/")
    repo = repo.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise RuntimeError("GitHub repository is unavailable")
    return repo


def in_window(value, start, end):
    when = timestamp(value)
    return when is not None and start <= when < end


def recent_30(value, end):
    when = timestamp(value)
    return when is not None and end - 30 * 86400 <= when < end


def lane_agent(branch):
    return next((agent for lane, agent in LANE_AGENTS.items()
                 if branch.startswith(f"task/{lane}/")), None)


def github_data(repo, start, end, owner=None):
    pulls = gh_list(f"repos/{repo}/pulls?state=all&per_page=100&sort=created&direction=asc")
    active = [p for p in pulls if in_window(p.get("created_at"), start, end)
              or in_window(p.get("merged_at"), start, end) or in_window(p.get("updated_at"), start, end)
              ]
    result = []
    for pull in active:
        number, created = pull["number"], pull.get("created_at")
        event = {"number": number, "branch": (pull.get("head") or {}).get("ref", ""),
                 "created_at": created, "merged_at": pull.get("merged_at")}
        if not in_window(created, start, end) and not in_window(pull.get("updated_at"), start, end):
            result.append(event)
            continue
        base = f"repos/{repo}/pulls/{number}"
        details = gh_api(base)
        reviews = gh_list(f"{base}/reviews?per_page=100")
        commits = gh_list(f"{base}/commits?per_page=100")
        files = gh_list(f"{base}/files?per_page=100")
        timeline = gh_list(f"repos/{repo}/issues/{number}/timeline?per_page=100")
        reviews = sorted((r for r in reviews if timestamp(r.get("submitted_at"))),
                         key=lambda r: timestamp(r["submitted_at"]))
        first_review = reviews[0] if reviews else {}
        reviewed_at = timestamp(first_review.get("submitted_at"))
        owner_reviews = [r for r in reviews if owner and (r.get("user") or {}).get("login", "").lower() == owner.lower()
                         and in_window(r.get("submitted_at"), start, end)]
        pushes = sum(e.get("event") == "committed" and len(e.get("parents") or []) <= 1
                     and reviewed_at is not None
                     and (t := timestamp((e.get("committer") or {}).get("date"))) is not None
                     and reviewed_at < t and start <= t < end for e in timeline)
        force = next((e for e in timeline if e.get("event") == "head_ref_force_pushed"), {})
        first_sha = (force.get("before_commit") or {}).get("sha")
        if not first_sha:
            dated = [(timestamp((c.get("commit", {}).get("committer") or {}).get("date")), c.get("sha"))
                     for c in commits]
            prior = [(t, sha) for t, sha in dated if t is not None and t <= (timestamp(created) or start)]
            first_sha = max(prior)[1] if prior else (details.get("head") or {}).get("sha")
        suites = gh_list(f"repos/{repo}/commits/{first_sha}/check-suites?per_page=100", "check_suites") if first_sha else []
        actions_suites = [s for s in suites if (s.get("app") or {}).get("slug") == "github-actions"
                          and (s.get("latest_check_runs_count") or 0) > 0]
        first_try_ci = None
        if actions_suites and all(s.get("status") == "completed" for s in actions_suites):
            bad = [s.get("conclusion") for s in actions_suites
                   if s.get("conclusion") not in ("success", "neutral", "skipped")]
            first_try_ci = next((c for c in bad if c != "cancelled"), None if bad else "success")
        head = (details.get("head") or {}).get("sha")
        checks = gh_list(f"repos/{repo}/commits/{head}/check-runs?filter=all&per_page=100", "check_runs") if head else []
        gate = [c for c in checks if c.get("name") == "single-track"
                and c.get("conclusion") in ("failure", "timed_out", "startup_failure")
                and in_window(c.get("completed_at"), start, end)]
        test_file = any(re.search(r"(^|/)(tests?|__tests__)(/|$)|(^|/)(test_[^/]+|[^/]+\.(test|spec)\.)",
                                  f.get("filename", "")) for f in files)
        result.append({**event,
                       "first_try_ci": first_try_ci, "rework_pushes": pushes,
                       "owner_changes": len(owner_reviews) if owner else None,
                       "owner_change_requests": [r for r in owner_reviews if r.get("state") == "CHANGES_REQUESTED"],
                       "changed_lines": (details.get("additions") or 0) + (details.get("deletions") or 0),
                       "evidence_missing": not any("check" in line.lower() and "dev" in line.lower()
                                                    for line in (details.get("body") or "").splitlines()) or not test_file,
                       "gate_failures": gate})
    cutoff = end - 30 * 86400
    bugs = []
    for issue in gh_list(f"repos/{repo}/issues?state=all&labels=bug&per_page=100"):
        if issue.get("pull_request"):
            continue
        refs = {int(n) for pair in re.findall(r"#(\d+)|/pull/(\d+)", issue.get("body") or "", re.I)
                for n in pair if n}
        created_at = timestamp(issue.get("created_at"))
        merged = [p for p in pulls if p.get("number") in refs and timestamp(p.get("merged_at")) is not None
                  and cutoff <= timestamp(p["merged_at"]) < end and created_at is not None
                  and timestamp(p["merged_at"]) < created_at < end]
        if merged:
            pr = max(merged, key=lambda p: timestamp(p["merged_at"]))
            bugs.append({"issue": issue["number"], "title": issue.get("title", ""),
                         "merged_at": pr["merged_at"], "lane": lane_agent((pr.get("head") or {}).get("ref", ""))})
    since = dt.datetime.fromtimestamp(cutoff, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = dt.datetime.fromtimestamp(end, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    commits = gh_list(f"repos/{repo}/commits?sha=main&since={since}&until={until}&per_page=100")
    reverts = [{"sha": c.get("sha", "")[:7], "message": c.get("commit", {}).get("message", "").splitlines()[0],
                "committed_at": c.get("commit", {}).get("committer", {}).get("date")}
               for c in commits if c.get("commit", {}).get("message", "").startswith("Revert")]
    return {"pull_requests": result, "bugs": bugs, "reverts": reverts, "owner_login": owner}


def percentile90(values):
    return sorted(values)[max(0, int(0.9 * len(values) - 0.1))] if values else None


def github_metrics(data, start, end):
    source = data.get("github")
    if source is None:
        return None
    blank = {"cycles": [], "pass": 0, "total": 0, "rework": 0,
             "owner": 0 if source.get("owner_login") else None, "bugs": 0, "scope": 0, "evidence": 0, "gate": 0}
    totals = defaultdict(lambda: {**blank, "cycles": []})
    for p in source["pull_requests"]:
        lane = lane_agent(p.get("branch", ""))
        targets = ["__company__"] + ([lane] if lane else [])
        created, merged = in_window(p.get("created_at"), start, end), in_window(p.get("merged_at"), start, end)
        for target in targets:
            m = totals[target]
            if merged:
                m["cycles"].append((timestamp(p["merged_at"]) - timestamp(p["created_at"])) / 86400)
            m["rework"] += p.get("rework_pushes", 0)
            m["gate"] += len(p.get("gate_failures", []))
            if source.get("owner_login"):
                m["owner"] += p.get("owner_changes") or 0
            if created:
                ci = p.get("first_try_ci")
                if ci:
                    m["total"] += 1
                    m["pass"] += ci == "success"
                m["scope"] += (p.get("changed_lines") or 0) > 400
                m["evidence"] += bool(p.get("evidence_missing"))
    for bug in source["bugs"]:
        if recent_30(bug.get("merged_at"), end):
            for target in ["__company__"] + ([bug["lane"]] if bug.get("lane") else []):
                totals[target]["bugs"] += 1
    totals["__company__"]["bugs"] += sum(recent_30(x.get("committed_at"), end) for x in source["reverts"])
    return totals


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
    gh_metrics = github_metrics(data, start, end)
    lane_names = {lane_agent(p.get("branch", "")) for p in (data.get("github") or {}).get("pull_requests", [])} - {None}
    groups.update(next((key for key, value in names.items() if value == name), f"__lane__:{name}")
                  for name in lane_names)
    company_key = "__company__"

    def label(group):
        return group[9:] if group.startswith("__lane__:") else names.get(group, "Unassigned")

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
            "github": gh_metrics[group if group == company_key else label(group)] if gh_metrics is not None else {},
        }

    rows = [
        (label(group), metrics(group))
        for group in sorted(groups, key=lambda g: label(g).lower())
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
    github = data.get("github") or {}
    for p in github.get("pull_requests", []):
        agent, pr = lane_agent(p.get("branch", "")) or "Company", f"PR #{p.get('number', 'n/a')}"
        ci = p.get("first_try_ci")
        if in_window(p.get("created_at"), start, end) and ci and ci not in ("success", "neutral", "skipped"):
            failures.append((agent, pr, f"first-try CI {ci}"))
        failures.extend((agent, pr, "owner changes requested") for _ in p.get("owner_change_requests", []))
    failures.extend((b.get("lane") or "Company", f"Issue #{b.get('issue', 'n/a')}",
                     f"post-merge bug: {b.get('title', '')}".rstrip())
                    for b in github.get("bugs", []) if recent_30(b.get("merged_at"), end))
    failures.extend(("Company", f"Commit {r.get('sha', '')}", f"post-merge bug: {r.get('message', '')}".rstrip())
                    for r in github.get("reverts", []) if recent_30(r.get("committed_at"), end))
    alerts = []
    for label, row in rows:
        if row["cycle_missing"]:
            alerts.append(f"{label}: cycle time missing for {row['cycle_missing']} task(s)")
        if row["failed_pct"] is not None and row["failed_pct"] > 10:
            alerts.append(f"{label}: failed runs {row['failed_pct']:.1f}% (>10%)")
        if row["p90"] is not None and row["p90"] > 3:
            alerts.append(f"{label}: cycle-time p90 {row['p90']:.2f}d (>3d)")
        gh = row["github"]
        if gh.get("total") and 100 * gh["pass"] / gh["total"] < 70:
            alerts.append(f"{label}: first-try CI {100 * gh['pass'] / gh['total']:.1f}% (<70%)")
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
        ] + github_cells(row["github"])
        output.append("| " + " | ".join(str(v).replace("|", "\\|") for v in cells) + " |")
    output += ["", "## Alerts", ""] + [f"- {a}" for a in report["alerts"] or ["None"]]
    output += ["", "## Failures", "", "| Agent | Issue | Status |", "| --- | --- | --- |"]
    output += [f"| {a} | {i} | {s} |" for a, i, s in report["failures"] or [("None", "n/a", "n/a")]]
    return "\n".join(output) + "\n"


def github_cells(m):
    if not m:
        return ["n/a (GitHub unavailable)"] * len(GITHUB_COLUMNS)
    cycles = m["cycles"]
    ci = f"{100*m['pass']/m['total']:.1f}% ({m['pass']}/{m['total']})" if m["total"] else "n/a (no checks)"
    owner = str(m["owner"]) if m["owner"] is not None else "n/a (owner unset)"
    return [f"{statistics.median(cycles):.2f}d" if cycles else "n/a (no merged PRs)",
            f"{percentile90(cycles):.2f}d" if cycles else "n/a (no merged PRs)", ci,
            str(m["rework"]), owner, str(m["bugs"]), str(m["scope"]), str(m["evidence"]), str(m["gate"])]


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
        data["github"] = github_data(github_repository(), start, end,
                                     os.environ.get("AC_SCORECARD_OWNER_GITHUB_LOGIN"))
        print(render_report(build_report(data, monday, start, end)), end="")
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

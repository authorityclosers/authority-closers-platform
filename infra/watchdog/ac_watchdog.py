#!/usr/bin/env python3
"""AC watchdog: scan Paperclip every minute, wake stuck work, tell the owner on Telegram.

No AI and no tokens. Reads the Paperclip database. With the owner-approved board
key (root profile `ac-watchdog`) it also acts, always through the task itself so
agents keep full task context: it resumes stalled assignees, unblocks tasks whose
blockers are done, and pings the CTO's lane task when the code lane turns FREE.
Questions from agents arrive as their own cards with answer buttons (handled by
ac_telegram_bot.py). Interim tool until the dispatcher (GitHub #86) takes over.

    ac_watchdog.py              scan, act, message the owner
    ac_watchdog.py --alert-only scan and message, but take no action
    ac_watchdog.py --dry-run    print what would happen; change nothing
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, "/opt/ac-watchdog")
import ac_telegram as tg  # noqa: E402

import psycopg  # noqa: E402

PAPERCLIP_CONFIG = Path("/home/acdev/.paperclip/instances/default/config.json")
STATE = Path("/var/lib/ac-watchdog/state.json")
STALL_MINUTES = 30
REPEAT_HOURS = 6
DRY_RUN = "--dry-run" in sys.argv
ACT = not DRY_RUN and "--alert-only" not in sys.argv and Path("/root/.paperclip/auth.json").exists()
LANE_TASK = "AUT-41"  # CTO's standing "Code lane coordinator" task
LANE_CHECK_SECONDS = 60
DEV_CHECKOUT = "/home/acdev/src/authority-closers-platform"
GH = "/home/acdev/.local/bin/gh"
LANES = ("sales-xray", "platform", "admin", "ui", "devenv")
# One checkout per lane; the Sales Xray lane keeps the dev checkout, so salesxray-dev shows its work live.
LANE_CHECKOUTS = {"sales-xray": DEV_CHECKOUT, "exclusive": DEV_CHECKOUT,
                  "platform": "/home/acdev/src/lanes/platform/authority-closers-platform",
                  "admin": "/home/acdev/src/lanes/admin/authority-closers-platform",
                  "ui": "/home/acdev/src/lanes/ui/authority-closers-platform",
                  "devenv": "/home/acdev/src/lanes/devenv/authority-closers-platform"}
LANE_LINE = re.compile(r"(?i)\blane\b\W{0,6}(sales-xray|platform|admin|ui|devenv)\b")
REPO = "authorityclosers/authority-closers-platform"
LAPTOP_HEARTBEAT = "/home/acdev/.local/state/ac-laptop/heartbeat"
LAPTOP_AGENTS = ("feeff44a-5bb6-49b3-a9e4-8a3fb36dda0e", "4e4ad6e2-5565-42fb-b115-d099e474179d",
                 "c39b879e-d352-4d90-8d0a-7311e471f473")
CEO_ID = "5c491a14-d699-477e-a7a6-4535afa5cd64"
ROOT_SPECIALIST_ID = "feeff44a-5bb6-49b3-a9e4-8a3fb36dda0e"  # Laptop Specialist · Claude (Root & Infra)
CTO_ID = "c31da688-a2d6-4600-bc35-e8852579f8f7"
CHIEF_ID = "cc27186a-9914-44b6-baf1-8fc651cbc007"  # Chief of Staff (Sol): the routine loop, owner order 30 Sep
LANE_START_HOLD_SECONDS = 600  # after starting a task, give it time to claim the lane
ESCALATE_MINUTES = 30  # an agent's question reaches the owner only if the CTO/CEO leaves it this long
HEADING = re.compile(r"^\s*(?:#{1,6}\s*|\*\*|__)?\s*`?(owner decision needed|board action needed)",
                     re.IGNORECASE | re.MULTILINE)
URL_CREDENTIALS = re.compile(r"://[^/@\s]+@")
KEY_VALUES = re.compile(r"(token|secret|password|key)=\S+", re.IGNORECASE)

SECTIONS = {
    "needs": "🟣 <b>Needs you</b>",
    "auto": "🤖 <b>Handled automatically</b>",
    "problem": "⚠️ <b>Problems</b>",
}


def clean(text: str | None, limit: int) -> str:
    text = URL_CREDENTIALS.sub("://***@", text or "")
    text = KEY_VALUES.sub(lambda m: m.group(1) + "=***", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def link(ident: str) -> str:
    return f'<a href="{tg.LINK.format(ident)}">{ident}</a>'


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        now = datetime.now(UTC).isoformat()
        return {"comments_since": now, "runs_since": now, "sent": {}}


def due(state: dict, key: str, hours: float) -> bool:
    last = state["sent"].get(key)
    return last is None or time.time() - last > hours * 3600


def act(*args: str) -> bool:
    return ACT and tg.paperclip(*args)[0]


def resume(issue_id: str, body: str) -> bool:
    return act("issue", "comment", issue_id, "--body", body, "--resume")


def still(conn: psycopg.Connection, issue_id: str, *statuses: str) -> bool:
    """AUT-366: re-read the issue right before changing it; a task the CEO parked in backlog meanwhile stays parked."""
    row = conn.execute("select status from issues where id = %s", (issue_id,)).fetchone()
    return bool(row) and row[0] in statuses


def as_acdev(command: str, timeout: int = 120) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["sudo", "-u", "acdev", "-H", "bash", "-lc", command],
                              capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def lane_state() -> dict | None:
    """Per-lane view from the gate: {"exclusive_free": bool, "lanes": {lane: {"free": bool, "holder": str}}}."""
    # Always main's gate, whatever branch the dev checkout is on.
    gate = "/home/acdev/.cache/ac_task_main.py"
    done = as_acdev(f"cd {DEV_CHECKOUT} && git fetch -q origin main && git show origin/main:scripts/ac_task.py > {gate}"
                    f" && python3 {gate} status --json")
    if done is not None and done.returncode == 0:
        try:
            return json.loads(done.stdout)
        except ValueError:
            pass
    # A gate without lanes: one exclusive lane.
    done = as_acdev(f"cd {DEV_CHECKOUT} && python3 scripts/ac_task.py status")
    if done is None:
        return None
    last = (done.stdout.strip().splitlines() or [""])[-1]
    if not last.startswith(("FREE", "BUSY")):
        return None
    return {"exclusive_free": last.startswith("FREE"), "lanes": {}}


def task_lane(description: str | None) -> str:
    match = LANE_LINE.search(description or "")
    return match.group(1).lower() if match else "exclusive"


def mention(agent_id: str, names: dict) -> str:
    return f"[@{names.get(agent_id, 'agent')}](agent://{agent_id})"


def gh_api(path: str) -> Any:
    """Read GitHub through the dev checkout's login (5,000 requests an hour; checks run every minute)."""
    done = subprocess.run(["sudo", "-u", "acdev", "-H", GH, "api", f"repos/{REPO}{path}"],
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise OSError(clean(done.stderr, 120))
    return json.loads(done.stdout)


CTO_APPROVAL = re.compile(r"CTO review:\s*approved\s+PR\s*#(\d+)\s*@\s*`?([0-9a-f]{7,40})", re.IGNORECASE)
CEO_APPROVAL = re.compile(r"Merge approved:\s*PR\s*#(\d+)\s*@\s*`?([0-9a-f]{7,40})", re.IGNORECASE)
# AUT-303 (ADR 0041, CTO Q1): the UI Guard may approve a UI-only PR; a CEO/CTO merge hold stops any merge.
UI_GUARD_ID = "2b432c77-38b1-4d69-b081-968b1846c194"
UI_GUARD_APPROVAL = re.compile(r"UI Guard approved:\s*PR\s*#(\d+)\s*@\s*`?([0-9a-f]{7,40})")
MERGE_HOLD = re.compile(r"Merge hold( released)?:\s*PR\s*#(\d+)\b")
UI_GUARD_PREFIXES = ("apps/sales-xray-web/app/", "apps/sales-xray-web/public/")
UI_GUARD_EXCLUDED = re.compile(r"(^|/)(package\.json|next\.config\.[^/]*|tsconfig[^/]*|\.?eslint[^/]*|vitest[^/]*"
                               r"|AGENTS\.md|CLAUDE\.md)$|(^|/)tests?/", re.IGNORECASE)
STUDIO_BRANCH = "task/ui/296-studio-"
REVIEW_GRACE_MINUTES = 20  # after checks pass, give the engineer's own CTO hand-off this long


CARRIED = re.compile(r"^Approval carried: PR #(\d+) @ [0-9a-f]{7,40} -> ([0-9a-f]{7,40}), PR diff unchanged")
REPLAY = [arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--replay=")]  # N or N@<ISO time>; dry run
if REPLAY:
    DRY_RUN, ACT = True, False


def approval_issue(conn: psycopg.Connection, author: str, pattern: re.Pattern, number: int, sha: str,
                   before: datetime | None = None, depth: int = 0) -> str | None:
    """AUT-60: the issue holding `author`'s approval of exactly PR #number @ sha, on any issue in the company
    (the earliest one). A head the watchdog carried an approval to counts as its parent's approval."""
    before = before or datetime.now(UTC) + timedelta(days=1)
    for issue_id, body in conn.execute(
        """select issue_id, body from issue_comments where author_agent_id = %s and body like %s and created_at < %s
           order by created_at""", (author, f"%#{number}%", before)):
        for n, approved_sha in pattern.findall(body or ""):
            if int(n) == number and sha.startswith(approved_sha.lower()):
                return str(issue_id)
    if depth >= 5:
        return None
    for (body,) in conn.execute(
        """select body from issue_comments where author_agent_id is null and body like 'Approval carried: PR #%%'
             and created_at < %s order by created_at""", (before,)):
        match = CARRIED.match(body or "")
        if match and int(match.group(1)) == number and sha.startswith(match.group(2)):
            parent = git("rev-parse", f"{sha}^1")
            return approval_issue(conn, author, pattern, number, parent, before, depth + 1) if parent else None
    return None


def git(*args: str) -> str:
    """Output of a git command in the dev checkout ('' on failure). Reads only, except fetches into refs/ac-watchdog/."""
    done = as_acdev(" ".join(["git", "-C", DEV_CHECKOUT, *args]), timeout=90)
    return done.stdout.strip() if done is not None and done.returncode == 0 else ""


def patch_id(sha: str) -> str:
    """git patch-id --stable of the PR's own diff: merge-base with main to head."""
    done = as_acdev(f'cd {DEV_CHECKOUT} && git diff "$(git merge-base origin/main {sha})" {sha} | git patch-id --stable',
                    timeout=90)
    return (done.stdout.split() or [""])[0] if done is not None and done.returncode == 0 else ""


def carried_from(number: int, sha: str, max_hops: int = 10) -> list[str]:
    """AUT-60 step 2 (CEO option A on AUT-73; AUT-276 multi-hop): commits whose approvals may carry to head sha,
    nearest first. Walks back through consecutive merge commits whose second parent is on main (no new author
    commits), keeping each first parent only while `git patch-id --stable` of the PR's own diff still equals the
    head's. The caller stops at the first commit that holds an approval.
    The third rule, every required check green on sha, is checked by the caller before approvals are read."""
    as_acdev(f"git -C {DEV_CHECKOUT} fetch -q origin main +refs/pull/{number}/head:refs/ac-watchdog/pr/{number}",
             timeout=90)
    found, cur = [], sha
    if len(git("rev-list", "--parents", "-n", "1", sha).split()) != 3:
        return found
    head_id = patch_id(sha)
    if not head_id:
        return found
    for _ in range(max_hops):
        parents = git("rev-list", "--parents", "-n", "1", cur).split()[1:]
        if len(parents) != 2:
            break
        first, second = parents
        on_main = as_acdev(f"git -C {DEV_CHECKOUT} merge-base --is-ancestor {second} origin/main")
        if on_main is None or on_main.returncode != 0 or patch_id(first) != head_id:
            break
        found.append(first)
        cur = first
    return found


def work_product_issue(conn: psycopg.Connection, number: int) -> str | None:
    row = conn.execute(
        """select issue_id from issue_work_products where type = 'pull_request'
             and (url like %s or external_id in (%s, %s)) order by is_primary desc, created_at limit 1""",
        (f"%/{REPO}/pull/{number}", str(number), f"{REPO}#{number}")).fetchone()
    return str(row[0]) if row else None


def pr_approvals(conn: psycopg.Connection, number: int, sha: str, before: datetime | None = None
                 ) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """(task issue, CTO approval issue, CEO approval issue, carried-from commit, UI Guard approval issue) for
    PR #number @ sha. The task is the issue holding the CTO approval, else the issue with the PR as a work product;
    never a parent. AUT-303: the UI Guard line carries over exactly like the CEO line (ADR 0041)."""
    cto = approval_issue(conn, CTO_ID, CTO_APPROVAL, number, sha, before)
    ceo = approval_issue(conn, CEO_ID, CEO_APPROVAL, number, sha, before)
    guard = approval_issue(conn, UI_GUARD_ID, UI_GUARD_APPROVAL, number, sha, before)
    parent = None
    if cto is None and ceo is None and guard is None:
        for candidate in carried_from(number, sha):
            cto = approval_issue(conn, CTO_ID, CTO_APPROVAL, number, candidate, before)
            ceo = approval_issue(conn, CEO_ID, CEO_APPROVAL, number, candidate, before)
            guard = approval_issue(conn, UI_GUARD_ID, UI_GUARD_APPROVAL, number, candidate, before)
            if cto or ceo or guard:
                parent = candidate
                break
    return cto or ceo or guard or work_product_issue(conn, number), cto, ceo, parent, guard


def merge_held(conn: psycopg.Connection, number: int) -> bool:
    """ADR 0041: the latest `Merge hold: PR #n` or `Merge hold released: PR #n` from the CEO or CTO decides."""
    held = False
    for (body,) in conn.execute(
        """select body from issue_comments where author_agent_id = any(%s::uuid[]) and body like %s
           order by created_at""", ([CEO_ID, CTO_ID], f"%Merge hold%#{number}%")):
        for match in MERGE_HOLD.finditer(body or ""):
            if int(match.group(2)) == number:
                held = not match.group(1)
    return held


def ui_guard_scope(number: int) -> str:
    """'' when GitHub's complete changed-file list, read now, is UI-only under ADR 0041 and no review thread is
    open; else why not. Fails closed: a read error, a short list or an unknown thread count is ineligible."""
    try:
        expected = int(gh_api(f"/pulls/{number}").get("changed_files") or 0)
        files: list[str] = []
        for page in range(1, 31):  # GitHub lists at most 3,000 files
            batch = gh_api(f"/pulls/{number}/files?per_page=100&page={page}")
            files += [f["filename"] for f in batch] + [f["previous_filename"] for f in batch if f.get("previous_filename")]
            if len(batch) < 100:
                break
    except Exception:  # noqa: BLE001 - unknown scope is not UI-only
        return "file list unreadable"
    if not files or len(set(files)) < expected:
        return "file list incomplete"
    outside = [f for f in files if not f.startswith(UI_GUARD_PREFIXES) or UI_GUARD_EXCLUDED.search(f)]
    if outside:
        return f"{len(outside)} file(s) outside the UI-only scope, e.g. {outside[0]}"
    threads = unresolved_threads(number)
    if threads != 0:
        return f"unresolved review threads: {threads if threads is not None else 'unknown'}"
    return ""


# T7 addendum: record an accepted approval in ac-studio-sync's state (as acdev, same flock, atomic replace) so the
# sync never pushes over the approved head. No state folder yet (sync not installed) means nothing to freeze.
FREEZE = r"""
import fcntl, json, os, sys, tempfile, time
from pathlib import Path
number, sha = sys.argv[1], sys.argv[2]
state = Path.home() / ".local/state/ac-studio-sync/state.json"
if not state.parent.is_dir():
    sys.exit(0)
with open("/run/ac-studio-sync/ac-studio-sync.lock", "a") as lock:
    for _ in range(90):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(1)
    else:
        sys.exit(3)
    data = json.loads(state.read_text()) if state.exists() else {}
    data.setdefault("approvals", {})[number] = sha
    with tempfile.NamedTemporaryFile("w", dir=state.parent, delete=False) as out:
        json.dump(data, out, indent=2, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(out.name, state)
"""


def freeze_studio_head(number: int, sha: str) -> bool:
    done = as_acdev(f"python3 -c {shlex.quote(FREEZE)} {int(number)} {shlex.quote(sha)}", timeout=120)
    return done is not None and done.returncode == 0


def unresolved_threads(number: int) -> int | None:
    """Open review conversations; main requires all of them resolved before a merge."""
    owner, name = REPO.split("/")
    query = ("query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p)"
             "{reviewThreads(first:100){nodes{isResolved}}}}}")
    try:
        done = subprocess.run(["sudo", "-u", "acdev", "-H", GH, "api", "graphql", "-f", f"query={query}",
                               "-f", f"o={owner}", "-f", f"n={name}", "-F", f"p={number}", "--jq",
                               "[.data.repository.pullRequest.reviewThreads.nodes[]|select(.isResolved|not)]|length"],
                              capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return int(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip().isdigit() else None


def merge(number: int, sha: str, branch: str) -> tuple[bool, str]:
    """Squash-merge exactly the approved commit with the dev checkout's GitHub login, then free the lane.
    A branch that really is behind main is brought up to date first; CI then runs again.
    AUT-276: any other refusal, or an update that fails or leaves the head where it was, returns the
    real error so the five-attempt CTO escalation runs."""
    try:
        done = subprocess.run(["sudo", "-u", "acdev", "-H", GH, "pr", "merge", str(number), "--squash",
                               "--match-head-commit", sha, "-R", REPO],
                              capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, type(error).__name__
    if done.returncode == 0:
        lane = branch.split("/")[1] if branch.count("/") == 2 else "exclusive"
        as_acdev(f"cd {LANE_CHECKOUTS.get(lane, DEV_CHECKOUT)} && python3 scripts/ac_task.py done")
        return True, ""
    err = clean(done.stderr or done.stdout, 160)
    try:
        behind = int(gh_api(f"/compare/main...{sha}").get("behind_by", 0))
    except Exception:  # noqa: BLE001 - unknown means not behind: the refusal escalates instead of looping
        behind = 0
    if behind <= 0:
        return False, err
    try:
        upd = subprocess.run(["sudo", "-u", "acdev", "-H", GH, "pr", "update-branch", str(number), "-R", REPO],
                             capture_output=True, text=True, timeout=120, check=False)
        rc, upd_err = upd.returncode, clean(upd.stderr or upd.stdout, 160)
        print(f"update-branch {number}: rc={rc} stdout={clean(upd.stdout, 160)!r} stderr={clean(upd.stderr, 160)!r}",
              file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as error:
        rc, upd_err = None, type(error).__name__
    head = sha
    for _ in range(3 if rc == 0 else 0):
        try:
            head = gh_api(f"/pulls/{number}")["head"]["sha"]
        except Exception:  # noqa: BLE001 - unknown head counts as not moved, so it escalates
            head = sha
        if head != sha:
            break
        time.sleep(2)
    if rc == 0 and head != sha:
        return False, f"behind main: branch updated to {head[:7]}, CI runs again, then it merges"
    return False, (f"branch update failed: {behind} commit(s) behind, head unchanged "
                   f"(rc={rc}: {upd_err or 'no output'}); merge refused: {err}")


def pull_requests(conn: psycopg.Connection, state: dict, names: dict, lines: list, main: str | None = None) -> None:
    """Owner decision 2026-09-28: the CEO approves merges. Green PR -> CTO review -> CEO approval -> merge.
    AUT-181 held merges while main ran; since 30 Sep (owner order) a merge waits only for a red or unknown
    main, because the single-track check keeps open pull requests on different files and a red main pauses
    every merge until it is fixed."""
    try:
        pulls = gh_api("/pulls?state=open&per_page=20")
    except (OSError, ValueError):
        return
    for pr in pulls:
        number, sha = pr["number"], pr["head"]["sha"]
        if pr.get("draft"):
            continue
        try:
            runs = gh_api(f"/commits/{sha}/check-runs?per_page=100")["check_runs"]
        except (OSError, ValueError, KeyError):
            continue
        if not runs or any(r["status"] != "completed" or r["conclusion"] not in ("success", "skipped", "neutral")
                           for r in runs):
            continue
        # AUT-60: approvals are found by PR number and head commit on any issue, not from AUT- keys in the PR.
        issue_id, cto_issue, ceo_issue, parent, guard_issue = pr_approvals(conn, number, sha)
        row = conn.execute("select identifier from issues where id = %s", (issue_id,)).fetchone() if issue_id else None
        if row is None:
            # No task holds an approval or the PR as a work product: ask the CTO on its lane task, not the owner.
            finished = max(datetime.fromisoformat((r.get("completed_at") or pr["updated_at"]).replace("Z", "+00:00"))
                           for r in runs)
            lane_task = conn.execute("select id from issues where identifier = %s", (LANE_TASK,)).fetchone()
            key = f"pr-untracked:{number}:{sha}"
            if lane_task and datetime.now(UTC) - finished >= timedelta(minutes=REVIEW_GRACE_MINUTES) \
                    and due(state, key, 10**6) and due(state, f"pr-cto:{number}:{sha}", 10**6):
                state["sent"][key] = time.time()
                if act("issue", "comment", str(lane_task[0]), "--body",
                       f"{mention(CTO_ID, names)} PR #{number} is green at `{sha[:7]}`, but no task has it as a work "
                       f"product. Review it and post `CTO review: approved PR #{number} @ {sha[:7]}` on its task, "
                       "or send it back there. The watchdog routes the PR to the task holding your approval."):
                    lines.append(("auto", f"• 🔀 PR #{number} is green with no task: sent to the CTO ({link(LANE_TASK)})",
                                  "", ""))
            continue
        ident, short = row[0], sha[:7]
        if parent:
            # Base-only branch update of an approved commit: record the carry on the task before merging.
            key = f"carried:{number}:{sha}"
            if due(state, key, 10**6):
                if not act("issue", "comment", issue_id, "--body",
                           f"Approval carried: PR #{number} @ {parent[:7]} -> {short}, PR diff unchanged"):
                    continue
                state["sent"][key] = time.time()
                lines.append(("auto", f"• 🔀 PR #{number} ({link(ident)}): approval carried over a branch update "
                                      "(PR diff unchanged, checks green)", issue_id, ident))
        if guard_issue and not ceo_issue:
            # ADR 0041: the UI Guard line merges only a UI-only PR, its file list read from GitHub every cycle.
            why = ui_guard_scope(number)
            if why:
                key = f"guard-scope:{number}:{sha}"
                if due(state, key, 10**6):
                    state["sent"][key] = time.time()
                    print(f"UI Guard approval not usable: PR #{number} @ {short}: {why}", file=sys.stderr)
                    act("issue", "comment", issue_id, "--body",
                        f"Watchdog: the UI Guard approved PR #{number} at `{short}`, but it cannot merge on that "
                        f"approval ({why}). It takes the normal route: CTO review, then CEO approval (ADR 0041).")
                guard_issue = None
        if ceo_issue or guard_issue:
            approver = "the CEO" if ceo_issue else "the UI Guard"
            if merge_held(conn, number):  # ADR 0041: a CEO/CTO `Merge hold: PR #n` stops any merge until released
                hold = f"merge-hold:{number}:{sha}:held"
                if due(state, hold, 10**6):
                    state["sent"][hold] = time.time()
                    print(f"merge held: PR #{number} @ {short}: Merge hold from the CEO or CTO", file=sys.stderr)
                continue
            if main not in ("green", "running"):  # owner order 30 Sep: only a red or unknown main holds merges
                hold = f"merge-hold:{number}:{sha}:{main}"
                if due(state, hold, 10**6):
                    state["sent"][hold] = time.time()
                    print(f"merge held: PR #{number} @ {short}: main is {main or 'unknown'}", file=sys.stderr)
                continue
            key = f"merge:{number}:{sha}"
            if not due(state, key, 10**6) or not ACT:
                continue
            if pr["head"]["ref"].startswith(STUDIO_BRANCH) and not freeze_studio_head(number, sha):
                print(f"merge waits: PR #{number} @ {short}: studio approval freeze not written", file=sys.stderr)
                continue
            state["sent"][key] = time.time()
            ok, err = merge(number, sha, pr["head"]["ref"])
            if ok:
                tg.paperclip("issue", "comment", issue_id, "--body",
                             f"Watchdog: merged PR #{number} at `{short}` on {approver}'s approval. "
                             "Staging deploys it next.")
                lines.append(("auto", f"• 🔀 Merged PR #{number} ({link(ident)}) on {approver}'s approval",
                              issue_id, ident))
            elif err.startswith("behind main: branch updated"):  # AUT-276: only a real update resets
                state["sent"].pop(key, None)  # try the merge again once CI is green on the updated branch
                lines.append(("auto", f"• 🔀 PR #{number} ({link(ident)}) was behind main: updated, merges after CI",
                              issue_id, ident))
            else:
                # GitHub has transient failures; retry the same approved commit every cycle, and only
                # after five failed attempts ask the CTO to look.
                attempts_key = f"merge-attempts:{number}:{sha}"
                attempts = int(state.get(attempts_key, 0)) + 1
                state[attempts_key] = attempts
                if attempts < 5:
                    state["sent"].pop(key, None)
                else:
                    threads = unresolved_threads(number)
                    act("issue", "comment", issue_id, "--body",
                        f"{mention(CTO_ID, names)} Watchdog: {approver} approved PR #{number} at `{short}`, but the "
                        f"merge failed {attempts} times: {err}. Unresolved review threads: "
                        f"{threads if threads is not None else 'unknown'}. Please look at it.")
                    lines.append(("problem", f"• 🔀 PR #{number} approved but the merge keeps failing: "
                                             f"<i>{tg.esc(err)}</i>", issue_id, ident))
            continue
        if cto_issue:
            key = f"pr-ceo:{number}:{sha}"
            if due(state, key, 10**6):
                state["sent"][key] = time.time()
                if act("issue", "comment", issue_id, "--body",
                       f"{mention(CEO_ID, names)} PR #{number} passed CI and the CTO's review. The owner delegated "
                       f"merge approval to you. Approve with `Merge approved: PR #{number} @ {short}`, or hold it and "
                       "ask the owner with options if it touches billing, payments, secrets or production data."):
                    lines.append(("auto", f"• 🔀 PR #{number} ({link(ident)}) sent to the CEO for merge approval",
                                  issue_id, ident))
            continue
        finished = max(datetime.fromisoformat((r.get("completed_at") or pr["updated_at"]).replace("Z", "+00:00")) for r in runs)
        key = f"pr-cto:{number}:{sha}"
        if datetime.now(UTC) - finished >= timedelta(minutes=REVIEW_GRACE_MINUTES) and due(state, key, 10**6):
            state["sent"][key] = time.time()
            if act("issue", "comment", issue_id, "--body",
                   f"{mention(CTO_ID, names)} PR #{number} is green at `{short}`. Review it; if it passes, post "
                   f"`CTO review: approved PR #{number} @ {short}` and mention the CEO. Otherwise send it back."):
                lines.append(("auto", f"• 🔀 PR #{number} ({link(ident)}) sent to the CTO for review", issue_id, ident))


DISPATCH_AFTER_MINUTES = 10


def dropped_push(state: dict, lines: list) -> None:
    """AUT-181: GitHub sometimes sends no push event for a main merge, so the head gets no CI and main never
    turns green. Ten minutes after such a head appeared, dispatch application.yml once for it. This only
    validates; the release engine deploys push runs, so staging picks the merge up with the next push."""
    try:
        head = gh_api("/commits/main")
        sha = head["sha"]
        appeared = datetime.fromisoformat(head["commit"]["committer"]["date"].replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001 - unknown head: do nothing this cycle
        return
    key = f"dispatched:{sha}"
    if not due(state, key, 10**6) or datetime.now(UTC) - appeared < timedelta(minutes=DISPATCH_AFTER_MINUTES):
        return
    try:
        suites = int(gh_api(f"/commits/{sha}/check-suites?per_page=1")["total_count"])
        runs = int(gh_api(f"/actions/runs?head_sha={sha}&per_page=1")["total_count"])
        still_head = gh_api("/commits/main")["sha"] == sha
    except Exception:  # noqa: BLE001 - unknown counts as "has a run": never dispatch blind
        return
    if suites or runs or not still_head or not ACT:
        return
    state["sent"][key] = time.time()
    try:
        done = subprocess.run(["sudo", "-u", "acdev", "-H", GH, "workflow", "run", "application.yml",
                               "--ref", "main", "-R", REPO], capture_output=True, text=True, timeout=60, check=False)
        rc, err = done.returncode, clean(done.stderr or done.stdout, 160)
    except (OSError, subprocess.SubprocessError) as error:
        rc, err = None, type(error).__name__
    print(f"dropped push: main {sha[:7]} had 0 check suites after {DISPATCH_AFTER_MINUTES} min; "
          f"dispatched application.yml rc={rc} {err}", file=sys.stderr)
    if rc == 0:
        lines.append(("auto", f"• 🔁 main <code>{sha[:7]}</code> got no CI (dropped push): dispatched a validation run",
                      "", ""))
    else:
        lines.append(("problem", f"• 🔁 main <code>{sha[:7]}</code> got no CI and the dispatch failed: "
                                 f"<i>{tg.esc(err)}</i>", "", ""))


# AUT-303 (release train R1): post the train's spooled events. ac-train-notify (T5) writes the release spool;
# ac-studio-sync (T7) writes the studio spool. Each file is posted once, then moved to done/ and kept 7 days.
TRAIN_SPOOLS = (Path("/var/lib/ac-release/notify"), Path("/var/lib/ac-studio/notify"))
TRAIN_STATUS_TASK = "AUT-72"
TRAIN_REVIEW_TASK = "AUT-296"
DEV_LEAD_ID = "d2071c40-8b1c-4170-9101-d418b2865395"  # Dev Environment Lead
TRAIN_KEEP_DAYS = 7
TRAIN_ALERT_REPEAT_HOURS = 6  # T5 rewrites a lasting condition every 10 min; comment on its issue at most this often
TRAIN_ALERT_MARK = "Train alert key: `{}`"


def train_event(conn: psycopg.Connection, state: dict, names: dict, lines: list, event: dict) -> bool:
    """Post one event; True when it is handled (posted or deliberately dropped) and may move to done/."""
    kind, key, text = event.get("kind"), str(event.get("key") or "").strip(), str(event.get("text") or "").strip()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if kind not in ("status", "alert", "review") or not key or not text:
        print(f"train event dropped: malformed ({kind!r}, key {key[:40]!r})", file=sys.stderr)
        return True

    def issue_id(ident: str) -> str | None:
        row = conn.execute("select id from issues where identifier = %s", (ident,)).fetchone()
        return str(row[0]) if row else None

    if kind == "status":
        target = issue_id(TRAIN_STATUS_TASK)
        return bool(target) and act("issue", "comment", target, "--body", text)
    if kind == "review":
        target = issue_id(TRAIN_REVIEW_TASK)
        pr = str(event.get("pr") or fields.get("pr") or "").lstrip("#")
        number = pr if pr.isdigit() else "n"
        return bool(target) and act(
            "issue", "comment", target, "--body",
            f"{mention(UI_GUARD_ID, names)} Studio PR #{number} is ready for your review: {text}\n\n"
            f"If it passes your checklist, post `UI Guard approved: PR #{number} @ <sha7>`.")
    # alert: one open critical issue per key, found by the key line in its description.
    mark = TRAIN_ALERT_MARK.format(key)
    row = conn.execute(
        """select id, identifier from issues where company_id = %s and description like %s
             and status not in ('done', 'cancelled') and hidden_at is null order by created_at limit 1""",
        (tg.COMPANY, "%" + re.sub(r"([\\%_])", r"\\\1", mark) + "%")).fetchone()
    repeat = f"train-alert:{key}"
    if row:
        if due(state, repeat, TRAIN_ALERT_REPEAT_HOURS) and act(
                "issue", "comment", str(row[0]), "--body", f"Watchdog: the train raised this alert again.\n\n{text}"):
            state["sent"][repeat] = time.time()
        return True  # deduplicated: no new issue while one is open
    first = text.splitlines()[0][:120]
    if not act("issue", "create", "-C", tg.COMPANY, "--title", f"Train alert: {first}", "--priority", "critical",
               "--status", "todo", "--assignee-agent-id", DEV_LEAD_ID,
               "--description", f"{text}\n\n{mark}\n\nRaised by the release train; posted by the watchdog (AUT-303). "
                                "Close this issue once the condition is fixed; a later alert with the same key opens "
                                "a new one."):
        return False
    state["sent"][repeat] = time.time()
    lines.append(("problem", f"• 🚆 Train alert: <i>{tg.esc(first)}</i>", "", ""))
    return True


def train_events(conn: psycopg.Connection, state: dict, names: dict, lines: list) -> None:
    if not ACT:
        return  # dry runs and alert-only runs leave the spool untouched
    for spool in TRAIN_SPOOLS:
        if not spool.is_dir():
            continue
        done = spool / "done"
        done.mkdir(mode=0o750, exist_ok=True)
        for path in sorted(spool.glob("*.json")):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                event = {}
            if not train_event(conn, state, names, lines, event if isinstance(event, dict) else {}):
                print(f"train event kept for the next run: {path.name} (board post failed)", file=sys.stderr)
                continue
            path.replace(done / f"{datetime.now(UTC):%Y%m%dT%H%M%S.%fZ}-{path.name}")
        cutoff = time.time() - TRAIN_KEEP_DAYS * 86400
        for old in done.glob("*.json"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass


UI_STUDIO_TASK = "AUT-66"
UI_MAKER_ID = "0a2ff332-c2f0-4318-b8f5-62dc1c86cb4d"
UI_AUTOSHIP_HOURS = 10**6  # PAUSED 29 Sep: auto-ship hijacked the live studio; redesign before re-enabling
UI_IDLE_MINUTES = 20


def ui_autoship(conn: psycopg.Connection, state: dict, names: dict, lines: list) -> None:
    """Every UI_AUTOSHIP_HOURS, ship the studio's changes to staging (via the UI Guard's normal PR path)."""
    if time.time() - state.get("ui_autoship_checked", 0) < 600:
        return
    state["ui_autoship_checked"] = time.time()
    row = conn.execute("select id from issues where identifier = %s", (UI_STUDIO_TASK,)).fetchone()
    if row is None:
        return
    issue_id = str(row[0])
    # The owner's last word wins: "hold shipping" pauses auto-ship, "resume shipping" or "ship now" restarts it.
    owner_says = conn.execute(
        """select lower(body) from issue_comments where issue_id = %s and author_user_id is not null
             and (body ~* '(hold|pause|stop)\\s+ship' or body ~* '(resume|start)\\s+ship' or body ~* 'ship\\s+now')
           order by created_at desc limit 1""", (issue_id,)).fetchone()
    if owner_says and re.search(r"(hold|pause|stop)\s+ship", owner_says[0]):
        return
    ship_now = bool(owner_says and re.search(r"ship\s+now", owner_says[0])) and \
        not state.get("ui_ship_now_done") == owner_says[0][:80]
    if not ship_now and time.time() - state.get("ui_autoship_at", 0) < UI_AUTOSHIP_HOURS * 3600:
        return
    checkout = LANE_CHECKOUTS["ui"]
    changed = as_acdev(f"cd {checkout} && git status --porcelain | head -1; "
                       f"git rev-list --count origin/main..HEAD 2>/dev/null")
    if changed is None:
        return
    out = [line for line in changed.stdout.splitlines() if line.strip()]
    ahead = int(out[-1]) if out and out[-1].strip().isdigit() else 0
    dirty = len(out) > (1 if out and out[-1].strip().isdigit() else 0)
    if not dirty and ahead == 0:
        return
    try:
        open_ui = [p for p in gh_api("/pulls?state=open&per_page=30") if p["head"]["ref"].startswith("task/ui/")]
    except (OSError, ValueError, KeyError):
        return
    if open_ui:
        return  # the last batch is still in review; the next one waits
    recent_maker = conn.execute(
        "select 1 from heartbeat_runs where agent_id = %s and (status = 'running' or finished_at > now() - %s::interval)",
        (UI_MAKER_ID, f"{UI_IDLE_MINUTES} minutes")).fetchone()
    if recent_maker and not ship_now:
        return  # the owner is mid-change; try again shortly
    body = (f"{mention(UI_GUARD_ID, names)} Auto-ship (the owner's standing rule: studio changes reach staging "
            f"every {UI_AUTOSHIP_HOURS}h): run **check it + ship it** now with the studio's current changes. "
            "Tests, typecheck and lint must pass. Then @mention the CTO. After it merges, start the next studio branch "
            "at once, carrying any new edits (stash, `start ui`, pop), so the owner can keep designing.")
    if act("issue", "comment", issue_id, "--body", body):
        state["ui_autoship_at"] = time.time()
        if ship_now:
            state["ui_ship_now_done"] = owner_says[0][:80]
        lines.append(("auto", f"• 🚀 UI studio: shipping the latest screen changes to staging ({link(UI_STUDIO_TASK)})",
                      issue_id, UI_STUDIO_TASK))


# Live progress for the owner (owner, 29 Sep: "the CEO and UI Maker ... say working for minutes and then don't give me
# any updates, I need to see"). When the owner has just written on a task and the CEO or UI Maker is running on it,
# post plain notes on that task: on it, still working (with what changed), finished/stopped. Plain comments with no
# mention and no --resume, so they never wake anyone.
LIVE_AGENTS = {UI_MAKER_ID: "UI Maker", CEO_ID: "CEO"}
LIVE_UPDATES = (3, 6, 10, 15)  # minutes after the start
RUN_LOGS = Path("/home/acdev/.paperclip/instances/default/data/run-logs")
IST = timezone(timedelta(hours=5, minutes=30))
NOT_OWNER = re.compile(r"^\s*(Watchdog:|\[@|⏳|✅|⚠️|\*\*Claude|\*\*Owner order|\*\*Owner priority)")


def latest_step(log_ref: str | None) -> str:
    """The agent's latest sentence from a Claude stream-json run log ('' if none)."""
    try:
        raw_lines = (RUN_LOGS / (log_ref or "-")).read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
    except OSError:
        return ""
    for raw in reversed(raw_lines):
        try:
            chunk = json.loads(raw).get("chunk", "")
        except ValueError:
            continue
        for line in reversed(chunk.splitlines()):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "message" and event.get("role") == "assistant"                     and str(event.get("content") or "").strip():
                return clean(str(event["content"]), 180)  # agy bridge (Gemini-style) events
            if isinstance(event, dict) and event.get("type") == "assistant":
                for part in (event.get("message") or {}).get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "text" and part.get("text", "").strip():
                        return clean(part["text"], 180)
    return ""


def studio_files(since: datetime) -> str:
    done = as_acdev("cd ~/src/lanes/ui/authority-closers-platform/apps/sales-xray-web && find . -type f "
                    f"-newermt @{int(since.timestamp())} -not -path './node_modules/*' -not -path './.next/*' "
                    "-printf '%f\n' | sort -u | head -6", timeout=30)
    files = [name for name in (done.stdout.split() if done and done.returncode == 0 else []) if name]
    return ("saved " + ", ".join(files)) if files else "no screen file saved yet"


# AUT-570 (30 Sep): off. The watchdog posts as a board user, so every note counted as an owner message: it reopened
# done tasks and woke the CEO (Opus) again for nothing (AUT-562: 8 extra wakes). The CLI cannot edit a comment in place,
# so no issue comments at all until a non-waking channel exists.
LIVE_COMMENTS = False


def live_progress(conn: psycopg.Connection, state: dict, names: dict) -> None:
    if not LIVE_COMMENTS:
        state.pop("live", None)
        return
    live = state.setdefault("live", {})
    now = datetime.now(UTC)
    running = set()
    for run_id, agent_id, started, issue_id, log_ref in conn.execute(
            """select id, agent_id, coalesce(started_at, created_at), context_snapshot->>'issueId', log_ref
               from heartbeat_runs where status = 'running' and agent_id = any(%s)""", (list(LIVE_AGENTS),)).fetchall():
        run_id = str(run_id)
        running.add(run_id)
        if not issue_id:
            continue
        entry = live.get(run_id)
        if entry is None:
            bodies = [body for (body,) in conn.execute(
                """select body from issue_comments where issue_id = %s and author_agent_id is null
                   and created_at > %s - interval '30 minutes' and created_at < %s + interval '2 minutes'""",
                (issue_id, started, started))]
            spoke = any(not NOT_OWNER.match(body or "") for body in bodies)
            entry = live[run_id] = {"issue": issue_id, "agent": str(agent_id), "started": started.timestamp(),
                                    "posts": 0, "skip": not spoke}
        if entry["skip"]:
            continue
        agent = LIVE_AGENTS.get(str(agent_id), names.get(agent_id, "Agent"))
        minutes = (now - started).total_seconds() / 60
        body = None
        if entry["posts"] == 0 and minutes >= 0.5:
            body = f"⏳ **{agent}** is working on this (started {started.astimezone(IST):%H:%M} IST)."
        elif 0 < entry["posts"] <= len(LIVE_UPDATES) and minutes >= LIVE_UPDATES[entry["posts"] - 1]:
            detail = latest_step(log_ref)
            if str(agent_id) == UI_MAKER_ID:
                detail = studio_files(started) + (f" · {detail}" if detail else "")
            body = f"⏳ Still working · {int(minutes)} min" + (f" · {detail}" if detail else "")
        if body and act("issue", "comment", issue_id, "--body", body):
            entry["posts"] += 1
    for run_id in [key for key in live if key not in running]:
        entry = live.pop(run_id)
        if entry.get("skip") or not entry.get("posts"):
            continue
        status, finished, error = conn.execute(
            "select status, finished_at, coalesce(error, '') from heartbeat_runs where id = %s", (run_id,)).fetchone()
        started = datetime.fromtimestamp(entry["started"], UTC)
        replied = conn.execute("""select 1 from issue_comments where issue_id = %s and author_agent_id = %s
                                  and created_at > %s limit 1""", (entry["issue"], entry["agent"], started)).fetchone()
        agent = LIVE_AGENTS.get(entry["agent"], "Agent")
        minutes = int(((finished or now) - started).total_seconds() / 60)
        if status != "succeeded":
            body = f"⚠️ **{agent}** stopped after {minutes} min ({status}{': ' + clean(error, 120) if error else ''})."
        elif not replied:
            body = f"✅ **{agent}** finished after {minutes} min without writing a reply."
        else:
            continue
        act("issue", "comment", entry["issue"], "--body", body)


def question_cards(conn: psycopg.Connection, state: dict, names: dict,
                   lines: list) -> list[tuple[str, list, str, str]]:
    """Agents' questions go to the CTO (or the CEO for the CTO's own) first; the owner sees a question
    only when it is addressed to them, comes from the CEO, or stays unanswered for ESCALATE_MINUTES."""
    cards = []
    for inter_id, issue_id, ident, kind, title, summary, payload, agent_id, to_agent, to_user, created in conn.execute(
        """select t.id, i.id, i.identifier, t.kind, t.title, t.summary, t.payload, t.created_by_agent_id,
                  t.addressee_agent_id, t.addressee_user_id, t.created_at
           from issue_thread_interactions t join issues i on i.id = t.issue_id
           where t.status not in ('answered','accepted','rejected','cancelled','expired')
           order by t.created_at"""
    ):
        who = names.get(agent_id, "An agent")
        if agent_id is not None and str(agent_id) != CEO_ID:
            # Chain of command: agents -> Chief of Staff -> (after ESCALATE_MINUTES) CEO. Never the owner.
            first = str(to_agent) if to_agent and str(to_agent) != str(agent_id) else (
                CEO_ID if str(agent_id) in (CTO_ID, CHIEF_ID) else CHIEF_ID)
            late = datetime.now(UTC) - created >= timedelta(minutes=ESCALATE_MINUTES)
            reviewer = CEO_ID if late else first
            since = created + timedelta(minutes=ESCALATE_MINUTES) if late else created
            key = f"routed:{inter_id}:{reviewer}"
            if due(state, key, 10**6):
                state["sent"][key] = time.time()
                # A new comment expires open question cards, so stay quiet when the reviewer was already
                # woken or @mentioned since the question was asked.
                woken = conn.execute("select 1 from heartbeat_runs where agent_id = %s and created_at > %s",
                                     (reviewer, since)).fetchone() or conn.execute(
                    "select 1 from issue_comments where issue_id = %s and created_at > %s and body like %s",
                    (issue_id, since - timedelta(minutes=5), f"%agent://{reviewer}%")).fetchone()
                ask = (f"{mention(reviewer, names)} {who} asked a question on this task "
                       f"(“{clean(title or summary, 80)}”)" + (f" and it has waited {ESCALATE_MINUTES} minutes"
                                                                    if late else "") +
                       ". Answer it in the card yourself. Only the CEO talks to the owner: if only the owner can "
                       "decide, the CEO asks the owner with options, recommended first.")
                if woken or act("issue", "comment", str(issue_id), "--body", ask):
                    lines.append(("auto", f"• ↪️ {tg.esc(who)}'s question on {link(ident)} went to "
                                          f"<b>{tg.esc(names.get(reviewer, '?'))}</b>, not you", str(issue_id), ident))
            elif datetime.now(UTC) - created >= timedelta(hours=2) and due(state, f"late:{inter_id}", REPEAT_HOURS):
                state["sent"][f"late:{inter_id}"] = time.time()
                lines.append(("problem", f"• ⏳ {tg.esc(who)}'s question on {link(ident)} has waited 2h+ "
                                         "for the CEO", str(issue_id), ident))
            continue
        key = f"question:{inter_id}"
        if not due(state, key, REPEAT_HOURS):
            continue
        state["sent"][key] = time.time()
        p = payload if isinstance(payload, dict) else json.loads(payload or "{}")
        asking = f"{who} is asking you"
        head = f"❓ <b>{tg.esc(asking)}</b>\n{link(ident)} · {tg.esc(clean(title or summary, 80))}"
        buttons: list[list[dict]] = []
        group, base = str(inter_id), {"issue_id": str(issue_id), "interaction_id": str(inter_id)}
        if kind == "ask_user_questions" and len(p.get("questions", [])) == 1 \
                and p["questions"][0].get("selectionMode", "single") == "single":
            q = p["questions"][0]
            body = f"\n\n<i>{tg.esc(clean(q.get('prompt'), 700))}</i>"
            card = head + body
            buttons = [[tg.button({**base, "kind": "respond", "question_id": q["id"], "option_id": o["id"],
                                   "label": o["label"], "group": group, "card": card}, o["label"])]
                       for o in q.get("options", [])[:6]]
        elif kind == "request_confirmation":
            body = f"\n\n<i>{tg.esc(clean(p.get('prompt'), 700))}</i>"
            card = head + body
            accept = p.get("acceptLabel") or "Approve"
            row = [tg.button({**base, "kind": "accept", "label": accept, "group": group, "card": card}, f"✅ {accept}")]
            if not p.get("rejectRequiresReason"):
                reject = p.get("rejectLabel") or "Reject"
                row.append(tg.button({**base, "kind": "reject", "label": reject, "group": group, "card": card}, f"✖️ {reject}"))
            buttons = [row]
        else:
            card = head + "\n\n<i>This question has several parts; answer it in Paperclip.</i>"
        buttons.append([{"text": "🔗 Open in Paperclip", "url": tg.LINK.format(ident)}])
        cards.append((card, buttons, str(issue_id), ident))
    return cards


def scan(conn: psycopg.Connection, state: dict) -> tuple[list[tuple[str, str, str, str]], list]:
    """Return (digest lines as (section, html, issue_id, ident), question cards)."""
    lines: list[tuple[str, str, str, str]] = []
    names = {k: n for i, n in conn.execute("select id, name from agents") for k in (i, str(i))}
    agent_status = dict(conn.execute("select id, status from agents"))

    # Decisions and board actions posted by agents as a heading or first line.
    announced: set[tuple[str, bool]] = set()
    for cid, created, body, issue_id, ident, title, author in conn.execute(
        """select c.id, c.created_at, c.body, i.id, i.identifier, i.title, c.author_agent_id from issue_comments c
           join issues i on i.id = c.issue_id
           where c.created_at > %s and c.author_agent_id is not null
             and (c.body ilike '%%Owner decision needed%%' or c.body ilike '%%Board action needed%%')
           order by c.created_at""", (state["comments_since"],)).fetchall():
        state["comments_since"] = max(state["comments_since"], created.isoformat())
        match = HEADING.search(body or "")
        key = f"comment:{cid}"
        if match is None or not due(state, key, 10**6):
            continue
        state["sent"][key] = time.time()
        owner = match.group(1).lower().startswith("owner")
        what = "Decision needed" if owner else "Board action needed"
        if str(author) != CEO_ID:
            woken = conn.execute("select 1 from heartbeat_runs where agent_id = %s and created_at > %s",
                                 (CEO_ID, created)).fetchone()
            if woken or act("issue", "comment", str(issue_id), "--body",
                            f"{mention(CEO_ID, names)} {names.get(author, 'An agent')} posted “{what}” here. "
                            "Only you talk to the owner. Resolve it yourself if you can; otherwise bring it to the "
                            "owner yourself as one decision with options, recommended first."):
                lines.append(("auto", f"• ↪️ {tg.esc(names.get(author, 'An agent'))}'s “{what}” on "
                                      f"{link(ident)} went to the <b>CEO</b>, not you", str(issue_id), ident))
            continue
        if (ident, owner) in announced:
            continue
        announced.add((ident, owner))
        if owner:
            lines.append(("needs", f"• <b>{what}</b>: {link(ident)} {tg.esc(clean(title, 70))}", str(issue_id), ident))
        else:
            # Owner order, 29 Sep: the CEO is the final overseer. Its board/root steps go back to it to execute
            # through the Root & Infra specialist, and the owner is not pinged.
            act("issue", "comment", str(issue_id), "--body",
                f"{mention(CEO_ID, names)} You are the final overseer: nobody else will pick this up. Create a task "
                f"for {mention(ROOT_SPECIALIST_ID, names)} with the exact steps and a done check, then verify it.")

    # Decision tasks: the CEO's reach the owner; unowned reviews and other agents' decision tasks go to the CEO.
    for issue_id, ident, title, creator, status in conn.execute(
        """select id, identifier, title, created_by_agent_id, status from issues
           where status not in ('done','cancelled') and hidden_at is null
             and ((title ilike 'Owner decision needed%%' and assignee_user_id is null)
                  or (status = 'in_review' and assignee_agent_id is null and assignee_user_id is null))"""):
        if status != "in_review" and (creator is None or str(creator) == CEO_ID):
            key = f"waiting:{ident}"
            if due(state, key, 24):
                state["sent"][key] = time.time()
                lines.append(("needs", f"• <b>Waiting for you</b>: {link(ident)} {tg.esc(clean(title, 70))}",
                              str(issue_id), ident))
            continue
        key = f"to-ceo:{ident}"
        if due(state, key, REPEAT_HOURS):
            state["sent"][key] = time.time()
            if act("issue", "update", str(issue_id), "--assignee-agent-id", CEO_ID):
                lines.append(("auto", f"• ↪️ {link(ident)} went to the <b>CEO</b> to review or decide, not you",
                              str(issue_id), ident))

    # Every open task has an owner: the parent's owner, else the Chief of Staff. Backlog assignment wakes nobody.
    for issue_id, ident, parent_agent in conn.execute(
        """select i.id, i.identifier, p.assignee_agent_id from issues i left join issues p on p.id = i.parent_id
           where i.status not in ('done','cancelled','in_review') and i.hidden_at is null
             and i.assignee_agent_id is null and i.assignee_user_id is null"""):
        owner = str(parent_agent or CHIEF_ID)
        key = f"assign:{ident}"
        if due(state, key, REPEAT_HOURS):
            state["sent"][key] = time.time()
            if act("issue", "update", str(issue_id), "--assignee-agent-id", owner):
                lines.append(("auto", f"• 👤 Gave {link(ident)} an owner: <b>{tg.esc(names.get(owner, '?'))}</b>",
                              str(issue_id), ident))
            else:
                lines.append(("problem", f"• 👤 {link(ident)} has no owner", str(issue_id), ident))

    # Assigned work nobody is doing.
    cutoff = datetime.now(UTC) - timedelta(minutes=STALL_MINUTES)
    for issue_id, ident, title, agent_id, updated, status in conn.execute(
        """select id, identifier, title, assignee_agent_id, updated_at, status from issues
           where status in ('todo','in_progress') and assignee_agent_id is not null
             and hidden_at is null and updated_at < %s""", (cutoff,)):
        if agent_status.get(agent_id) == "running":
            continue
        if status == "todo" and "engineer" in names.get(agent_id, "").lower():
            continue  # queued engineering work is started by the lane picker below
        key = f"stalled:{ident}"
        if due(state, key, REPEAT_HOURS):
            state["sent"][key] = time.time()
            minutes = int((datetime.now(UTC) - updated).total_seconds() // 60)
            who = tg.esc(names.get(agent_id, "?"))
            if resume(str(issue_id), f"Watchdog: no activity on this task for {minutes} minutes and nobody is "
                      "running it. Please resume now. If something blocks you, post one comment naming the blocker."):
                lines.append(("auto", f"• ⏰ Woke <b>{who}</b> on {link(ident)} (idle {minutes} min)", str(issue_id), ident))
            else:
                lines.append(("problem", f"• ⏸ {link(ident)} stalled {minutes} min ({who} idle)", str(issue_id), ident))

    # Blocked work whose blockers are all finished.
    for issue_id, ident, title in conn.execute(
        """select b.id, b.identifier, b.title from issues b
           where b.status = 'blocked'
             and exists (select 1 from issue_relations r where r.related_issue_id = b.id and r.type = 'blocks')
             and not exists (select 1 from issue_relations r join issues x on x.id = r.issue_id
                             where r.related_issue_id = b.id and r.type = 'blocks'
                               and x.status not in ('done','cancelled'))"""):
        key = f"unblockable:{ident}"
        if due(state, key, REPEAT_HOURS):
            state["sent"][key] = time.time()
            if not still(conn, str(issue_id), "blocked"):
                continue  # AUT-366: moved meanwhile (for example parked in backlog): leave it alone
            if act("issue", "update", str(issue_id), "--status", "todo") and resume(
                    str(issue_id), "Watchdog: every blocker of this task is done, so it is unblocked. Please resume."):
                lines.append(("auto", f"• 🔓 Unblocked {link(ident)} (all blockers done)", str(issue_id), ident))
            else:
                lines.append(("problem", f"• 🔓 {link(ident)} can be unblocked (all blockers done)", str(issue_id), ident))

    # Blockers nobody owns.
    for issue_id, ident, title, blocked in conn.execute(
        """select x.id, x.identifier, x.title, b.identifier from issue_relations r
           join issues x on x.id = r.issue_id join issues b on b.id = r.related_issue_id
           where r.type = 'blocks' and x.assignee_agent_id is null and x.assignee_user_id is null
             and x.status not in ('done','cancelled') and b.status not in ('done','cancelled')"""):
        key = f"unowned:{ident}"
        if due(state, key, 12):
            state["sent"][key] = time.time()
            lines.append(("problem", f"• 🧱 {link(ident)} blocks {link(blocked)} but has no owner", str(issue_id), ident))

    # Release engine: a failed deploy pauses staging and nobody else is told.
    try:
        release = subprocess.run(["ac-release", "status"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        release = ""
    for line in release.splitlines():
        if "FAILED" in line or re.match(r"^staging\s.*\spaused$", line.strip()):
            key = f"release:{line.strip()}"
            if due(state, key, REPEAT_HOURS):
                state["sent"][key] = time.time()
                lines.append(("problem", f"• 🚨 Release engine: <code>{tg.esc(clean(line.strip(), 150))}</code> "
                                         "(staging deploys stop until someone resumes it)", "", ""))

    # Laptop Specialists work only while Suyash's laptop bridge checks in (pull-based; see ac-laptop-queue).
    try:
        laptop_online = time.time() - Path(LAPTOP_HEARTBEAT).stat().st_mtime < 120
    except OSError:
        laptop_online = False
    for agent_id, status in conn.execute("select id, status from agents where id = any(%s)", (list(LAPTOP_AGENTS),)):
        if laptop_online and status in ("paused", "error"):
            if act("agent", "resume", str(agent_id)):
                lines.append(("auto", f"• 💻 Laptop online: <b>{tg.esc(names.get(agent_id, '?'))}</b> is active", "", ""))
        elif not laptop_online and status in ("idle", "error"):
            if act("agent", "pause", str(agent_id)):
                lines.append(("auto", f"• 💻 Laptop offline: paused <b>{tg.esc(names.get(agent_id, '?'))}</b>", "", ""))

    # UI studio auto-ship: the owner keeps designing in AUT-66; every few hours the studio's changes go to staging.
    ui_autoship(conn, state, names, lines)
    live_progress(conn, state, names)

    # Failed agent runs.
    for run_id, created, agent_id, code, error in conn.execute(
        """select id, created_at, agent_id, error_code, error from heartbeat_runs
           where status = 'failed' and created_at > %s order by created_at""", (state["runs_since"],)):
        state["runs_since"] = max(state["runs_since"], created.isoformat())
        key = f"run:{run_id}"
        if due(state, key, 10**6):
            state["sent"][key] = time.time()
            lines.append(("problem", f"• ❌ <b>{tg.esc(names.get(agent_id, '?'))}</b> run failed: "
                                     f"<i>{tg.esc(clean(error or code, 120))}</i>", "", ""))

    # Lanes: start the next runnable engineering task in every free lane; tasks without a lane are exclusive.
    # AUT-366: only todo, or blocked with every blocker done. Backlog is the CEO's parking (AUT-72 focus freeze):
    # only the CEO takes a task out of backlog, so backlog tasks are never picked, started or nudged.
    pr_cards: list[tuple[str, list, str, str]] = []
    if time.time() - state.get("lane_checked", 0) >= LANE_CHECK_SECONDS:
        state["lane_checked"] = time.time()
        view = lane_state()
        if view is not None:
            free = {lane for lane, info in view.get("lanes", {}).items() if info.get("free")}
            if view.get("exclusive_free"):
                free.add("exclusive")
            runnable = conn.execute(
                """select i.id, i.identifier, i.status, i.description from issues i
                   join agents a on a.id = i.assignee_agent_id
                   where i.hidden_at is null and a.name ilike '%%engineer%%'
                     and (i.status = 'todo' or (i.status = 'blocked'
                          and exists (select 1 from issue_relations r where r.related_issue_id = i.id and r.type = 'blocks')
                          and not exists (select 1 from issue_relations r join issues x on x.id = r.issue_id
                                          where r.related_issue_id = i.id and r.type = 'blocks'
                                            and x.status not in ('done', 'cancelled'))))
                   order by case i.priority when 'critical' then 0 when 'high' then 1 when 'medium' then 2 else 3 end,
                            i.created_at""").fetchall()
            for issue_id, ident, status, description in runnable:
                lane = task_lane(description)
                if lane == "exclusive" and view.get("lanes") and not view.get("exclusive_free")                         and due(state, f"no-lane:{ident}", 10**6):
                    state["sent"][f"no-lane:{ident}"] = time.time()
                    if act("issue", "comment", str(issue_id), "--body",
                           f"{mention(CHIEF_ID, names)} This task has no `Lane:` line, so it waits until every lane is "
                           "free. Add `Lane: sales-xray|platform|admin|devenv` to its spec card unless it truly must run alone."):
                        lines.append(("auto", f"• 🛣 {link(ident)} has no lane: asked the Chief of Staff to add one",
                                      str(issue_id), ident))
                if lane not in free or time.time() - state.get(f"lane_started:{lane}", 0) < LANE_START_HOLD_SECONDS:
                    continue
                how = ("python3 scripts/ac_task.py start <issue>-<short-name>" if lane == "exclusive"
                       else f"python3 scripts/ac_task.py start {lane} <issue>-<short-name>")
                if not still(conn, str(issue_id), status):
                    continue  # AUT-366: moved meanwhile (for example parked in backlog): leave it alone
                ok = (status == "todo" or act("issue", "update", str(issue_id), "--status", "todo")) and resume(
                    str(issue_id), f"Watchdog: the {lane} lane is FREE and this is its next task. "
                                   f"From your lane checkout, start now with `{how}`.")
                if ok:
                    state[f"lane_started:{lane}"] = time.time()
                    # An exclusive task takes everything; a lane task rules out an exclusive start.
                    free = set() if lane == "exclusive" else free - {lane, "exclusive"}
                    lines.append(("auto", f"• 🟢 {lane} lane: started {link(ident)}", str(issue_id), ident))
                elif due(state, f"start-failed:{ident}", REPEAT_HOURS):
                    state["sent"][f"start-failed:{ident}"] = time.time()
                    lines.append(("problem", f"• 🟢 {link(ident)} could not be started in the {lane} lane",
                                  str(issue_id), ident))
            everything_free = bool(view.get("exclusive_free"))
            if everything_free and not runnable and not state.get("all_free"):
                row = conn.execute("select id from issues where identifier = %s", (LANE_TASK,)).fetchone()
                if row and resume(str(row[0]), "Watchdog: every lane is FREE and no engineering task is queued. "
                                               "Queue the next ones: assign the engineer, add a Lane: line, and use "
                                               "todo or Blocked-by links."):
                    lines.append(("auto", f"• 🟢 All lanes free, queue empty: pinged the Chief of Staff ({link(LANE_TASK)})", "", ""))
            if not DRY_RUN:
                state["all_free"] = everything_free
        dropped_push(state, lines)
        pull_requests(conn, state, names, lines, (view or {}).get("main"))
    train_events(conn, state, names, lines)

    return lines, pr_cards + question_cards(conn, state, names, lines)


def digest(lines: list[tuple[str, str, str, str]]) -> str:
    parts = ["<b>🛎 AC Ops</b>"]
    for section, title in SECTIONS.items():
        chosen = [html for s, html, _, _ in lines if s == section]
        if chosen:
            parts.append(f"\n{title}\n" + "\n".join(chosen))
    parts.append("\n<i>Reply to this message to comment on a task · /status</i>")
    return "\n".join(parts)


def replay(connection_string: str) -> int:
    """--replay=N[@<ISO time>]: how the PR rules read PR #N at its last head, from comments before that time.
    Prints only; no merges, comments or state changes."""
    with psycopg.connect(connection_string) as conn:
        for spec in REPLAY:
            number, _, at = spec.partition("@")
            before = datetime.fromisoformat(at.replace("Z", "+00:00")) if at else None
            pr = gh_api(f"/pulls/{number}")
            sha = pr["head"]["sha"]
            runs = gh_api(f"/commits/{sha}/check-runs?per_page=100")["check_runs"]
            green = bool(runs) and all(r["status"] == "completed" and r["conclusion"] in ("success", "skipped", "neutral")
                                       for r in runs)
            issue_id, cto, ceo, parent, guard = pr_approvals(conn, int(number), sha, before)
            ident = {str(i): d for i, d in conn.execute("select id, identifier from issues where id = any(%s::uuid[])",
                                                        ([x for x in (issue_id, cto, ceo, guard) if x],))}
            print(f"PR #{number} @ {sha[:7]} (comments before {before or 'now'}): checks green={green} "
                  f"task={ident.get(issue_id)} CTO approval on {ident.get(cto)} CEO approval on {ident.get(ceo)} "
                  + (f"carried from {parent[:7]} (one merge of main, patch-id equal)" if parent else "no carry"))
            scope = ui_guard_scope(int(number)) if guard and not ceo else ""
            print(f"  UI Guard approval on {ident.get(guard)}; scope: {'n/a' if not guard or ceo else scope or 'UI-only, threads resolved'}"
                  f"; merge hold: {merge_held(conn, int(number))}")
            if scope:
                guard = None
            action = ("merge with --match-head-commit " + sha[:7] if (ceo or guard) and green
                      else "ask the CEO" if cto and green else "ask the CTO" if green else "wait for checks")
            print(f"  -> would: {'post Approval carried, then ' if parent else ''}{action} (on {ident.get(issue_id)})")
    return 0


def main() -> int:
    connection_string = json.loads(PAPERCLIP_CONFIG.read_text())["database"]["connectionString"]
    if REPLAY:
        return replay(connection_string)
    state = load_state()
    with psycopg.connect(connection_string) as conn:
        lines, cards = scan(conn, state)
    state["sent"] = {k: v for k, v in state["sent"].items() if v > time.time() - 7 * 86400}
    if DRY_RUN:
        if lines:
            print(digest(lines))
        for card, buttons, _, _ in cards:
            print("\n---- card ----\n" + card + "\n[buttons] " + " | ".join(b["text"] for row in buttons for b in row))
        if not lines and not cards:
            print("(nothing to send)")
        return 0
    for card, buttons, issue_id, ident in cards:
        message_id = tg.send(card, buttons, purpose="decisions")
        if message_id:
            tg.remember_message(message_id, issue_id, ident)
    # Each kind of line goes to its own place: decisions, dev updates, alerts (see /route in the bot).
    for section, purpose in (("needs", "decisions"), ("auto", "dev"), ("problem", "alerts")):
        chosen = [line for line in lines if line[0] == section]
        if not chosen:
            continue
        message_id = tg.send(digest(chosen), purpose=purpose)
        # Replying to a message comments on its task when it concerns exactly one task.
        tasks = {(i, d) for _, _, i, d in chosen if i}
        if message_id and len(tasks) == 1:
            issue_id, ident = next(iter(tasks))
            tg.remember_message(message_id, issue_id, ident)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

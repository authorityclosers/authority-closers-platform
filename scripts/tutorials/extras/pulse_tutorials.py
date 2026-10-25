# ruff: noqa: E501, S603, S607
# (the video list is data; sudo runs the fixed task route)
"""Keeps AC's Pulse Work project "Tutorials v2" in step with the tutorials coverage map, through the AC
task route (ac-pulse-tasks: fixed operations inside AC's organisation). One task per video, marker
"tutv2:<slug>". The project is created once; its id is kept in ~/sx-tut/pulse-tutorials.json.

    python3 pulse_tutorials.py          dry run (prints what it would do)
    python3 pulse_tutorials.py --commit apply
"""

import json
import subprocess
import sys
from pathlib import Path

TASKS = "/usr/local/bin/ac-pulse-tasks"
STATE = Path.home() / "sx-tut" / "pulse-tutorials.json"
COMMIT = "--commit" in sys.argv
DRIVE = "Drive: Sales X-Ray Tutorials/2026-10-25 (per language, Index sheet) and Sales X-Ray Tutorials/v2/library."

# (slug, title, status, priority, notes)
VIDEOS = [
    (
        "t1",
        "T1 Join the Sales X-Ray testers",
        "done",
        "high",
        "Done 25 Oct: en/hi/mr, 9:16 + 16:9, captions, scripts (.docx/.txt), voice files. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "t2",
        "T2 Install from Google Play, or move from the old app",
        "done",
        "high",
        "Done 25 Oct: en/hi/mr, 9:16 + 16:9, captions, scripts (.docx/.txt), voice files. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "t3",
        "T3 Sign in inside the app",
        "done",
        "high",
        "Done 25 Oct: en/hi/mr, 9:16 + 16:9, captions, scripts (.docx/.txt), voice files. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "t4",
        "T4 First steps: permissions, phone setup, theme",
        "done",
        "high",
        "Done 25 Oct: en/hi/mr, 9:16 + 16:9, captions, scripts (.docx/.txt), voice files. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "t5",
        "T5 If something hangs: Reload, Refresh app data",
        "done",
        "high",
        "Done 25 Oct: en/hi/mr, 9:16 + 16:9, captions, scripts (.docx/.txt), voice files. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "wa",
        "WhatsApp tester messages, day 1/3/7/14 (en/hi/mr)",
        "done",
        "high",
        "In the Drive pack folder 'WhatsApp messages' (.txt, .docx, Roman script too). Uses the Alpha opt-in link.",
    ),
    (
        "yt-plan",
        "YouTube channel plan and channel art",
        "done",
        "high",
        "Shared notes youtube-channel-plan-20261025.md; banner and avatar in the pack's 'YouTube channel' folder. Creating the channel is the owner's step.",
    ),
    (
        "04",
        "04 Call a lead and log how it went (v0.88 remake)",
        "done",
        "high",
        "v0.88 remake done 25 Oct: one-tap Call, How did it go, History, Save and call. Reel 24-25 s, YouTube 2:16-2:34, en/hi/mr. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "13",
        "13 Lead stages and the Board (Lead OS)",
        "done",
        "high",
        "Done 25 Oct (v0.88): nine stages, the strip, Move sheet, one-tap Call, stage History, Pipeline numbers. Reel 34-37 s, YouTube 1:32-1:45, en/hi/mr. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "14",
        "14 My work and quick notes",
        "done",
        "normal",
        "Done 25 Oct (v0.88): My work for today, yesterday, this week; the Note button. Reel 25 s, YouTube 46-58 s, en/hi/mr. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "15",
        "15 All leads: filter, sort, saved views",
        "done",
        "normal",
        "Done 25 Oct (v0.88): Filter and sort, search, chips, saved views, select many. Reel 35-38 s, YouTube 61-73 s, en/hi/mr. Dev's Leads screen has since changed (Now / All leads / More): re-shoot when that ships. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "16",
        "16 Never lose a change (Not sent yet / All changes saved)",
        "done",
        "normal",
        "Done 25 Oct (v0.88): saved on the phone first, All changes saved, Not sent yet and Try again, never reinstall, Refresh app data. Reel 45-52 s, YouTube 50-58 s, en/hi/mr. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "tasks-remind",
        "Tasks tab and Remind (v0.89)",
        "done",
        "high",
        "Done 25 Oct (video 17, v0.89 screens): Tasks with Overdue, Today and Upcoming, Done, Do it later, and Remind on a lead. Reel 29-30 s, YouTube 47-52 s, en/hi/mr. https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi",
    ),
    (
        "billing",
        "Billing set: buy a plan, top up, invoices, refund, cancel renewal, Plan & usage",
        "open",
        "high",
        "Fixture ready: /review-fixture/billing-journey (6d7bdc1a). Prices a buyer sees are fine; never internal cost.",
    ),
    (
        "onboarding",
        "Set up your business (onboarding steps)",
        "open",
        "high",
        "Fixture ready: /review-fixture/sign-in?step=setup...",
    ),
    (
        "06",
        "06 Read your call Report and Brain 4.0 score",
        "open",
        "normal",
        "Storyboard ready; check against v0.88.",
    ),
    (
        "08",
        "08 Chats: every lead message in one inbox",
        "open",
        "normal",
        "Storyboard ready; check against v0.88.",
    ),
    (
        "03",
        "03 Add leads, one at a time or a whole list",
        "open",
        "normal",
        "Storyboard ready; v0.88 changed the list.",
    ),
    ("12", "12 Upload a recording", "open", "normal", "v1 only; remake."),
    ("11", "11 My coaching", "open", "normal", "v1 only; remake."),
    ("09", "09 Team, roles and invites", "open", "normal", "v1 only; remake."),
    (
        "10",
        "10 Taking leads from Meta and Google",
        "open",
        "normal",
        "v1 only; remake after the Meta work lands.",
    ),
    (
        "07",
        "07 Set up lead stages and pipelines",
        "open",
        "normal",
        "v1 only; remake for Lead OS L4 steps.",
    ),
    ("00", "00 Sales X-Ray: the full tour", "open", "normal", "Remake last."),
    ("rules", "Lead rules and assignment", "open", "normal", "Missing."),
    ("ready-msg", "Ready WhatsApp and SMS messages", "open", "normal", "Missing."),
    ("ai-replies", "AI replies in Chats", "open", "normal", "Missing."),
    ("lead-delete", "Delete a lead safely", "open", "normal", "Missing (fixture lead-delete)."),
    ("private", "Mark a call private", "open", "normal", "Missing."),
    ("prospect", "Prospect profile", "open", "normal", "Missing (fixture prospects)."),
    ("document", "Document view and Word file", "open", "normal", "Missing (fixture document)."),
    (
        "delete-account",
        "Delete your account and your data",
        "open",
        "normal",
        "Missing (fixture delete-account).",
    ),
    (
        "report-problem",
        "Report a problem and Your reports",
        "open",
        "normal",
        "Missing (fixture bug-report).",
    ),
    (
        "feedback",
        "The feedback card and What's new",
        "open",
        "normal",
        "Missing (fixture feedback).",
    ),
    ("team-coaching", "Team coaching", "open", "normal", "Owners and managers."),
    ("insights", "Organisation insights", "open", "normal", "Owners and managers."),
    ("seller-profile", "Salesperson profile", "open", "normal", "Owners and managers."),
    ("ai-level", "AI level per seller", "open", "normal", "Owners and managers."),
    (
        "developers",
        "Developers: API keys, webhooks, connect an AI assistant",
        "open",
        "normal",
        "Fixtures developers, ai-apps.",
    ),
    ("admin-bugs", "Admin: triage bug reports (/bugs)", "open", "normal", "Staff."),
    ("admin-feedback", "Admin: read feedback (/feedback)", "open", "normal", "Staff."),
    (
        "review",
        "Dipak's Report review in Admin (Review 2.0) and gold review on the phone",
        "open",
        "normal",
        "Staff.",
    ),
    (
        "pulse-staff",
        "Pulse for AC staff: tasks, chat, HQ",
        "open",
        "normal",
        "Staff; separate app.",
    ),
    (
        "academy",
        "Academy (learner app): programs, practice, certificates",
        "open",
        "normal",
        "Needs Academy fixtures or a QA learner.",
    ),
    ("coach", "Coach Studio", "open", "normal", "Coaches."),
]


def call(ops, dry):
    req = {"dry": dry, "ops": ops}
    out = subprocess.run(
        ["sudo", "-n", TASKS, "--batch", "-"],
        input=json.dumps(req, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout)
    if "error" in data:
        raise SystemExit(data["error"])
    return [r["r"] for r in data["results"]]


state = json.loads(STATE.read_text()) if STATE.exists() else {}
if not state.get("project"):
    r = call(
        [
            {
                "op": "project",
                "fields": {
                    "name": "Tutorials v2",
                    "description": "Sales X-Ray how-to videos in brand B: 9:16 reels, 16:9 tutorials, transcripts, captions and "
                    "translations (en, hi, mr). Coverage map: shared notes tutorials-coverage-20261025.md. "
                    "Owner: the tutorials session (local_28fa44a5).",
                },
            }
        ],
        dry=not COMMIT,
    )[0]
    print("project", r)
    if COMMIT:
        state["project"] = r["id"]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
project = state.get("project")
if not project:
    print(f"dry run: would create the project and {len(VIDEOS)} tasks")
    raise SystemExit(0)
# Tasks already made are updated by id: ensure doesn't find them again by marker (it makes copies).
known = state.get("tasks", {})
ops = []
for slug, title, _status, priority, notes in VIDEOS:
    if slug in known:
        continue
    ops.append(
        {
            "op": "ensure",
            "marker": f"tutv2:{slug}",
            "fields": {
                "title": f"Video: {title}",
                "priority": priority,
                "tags": [],
                "notes": f"{notes}\n\n{DRIVE}",
                "projectId": project,
            },
        }
    )
made = call(ops, dry=not COMMIT) if ops else []
fresh = [v for v in VIDEOS if v[0] not in known]
ids = {**known, **{slug: r["id"] for (slug, *_), r in zip(fresh, made, strict=True)}}
# Only changed statuses are sent: the route adds a note to the task on every move.
sent = state.get("status", {})
moves = [
    {"op": "move", "id": ids[slug], "status": status, "note": notes}
    for slug, _t, status, _p, notes in VIDEOS
    if status != "open" and sent.get(slug) != status
]
moved = call(moves, dry=not COMMIT) if moves else []
print(
    f"tasks ensured {len(made)} (new {sum(1 for r in made if r.get('created'))}), statuses set {len(moved)}"
    + ("" if COMMIT else " [dry]")
)
if COMMIT:
    state["tasks"] = ids
    state["status"] = {slug: status for slug, _t, status, _p, _n in VIDEOS}
    STATE.write_text(json.dumps(state, indent=1))

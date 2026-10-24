"""Where people get stuck in Sales X-Ray: the weekly friction report (owner, 25 Oct 2026:
"automatically find where users stop, which screen they get stuck on, where they try to tap,
and why ... a weekly report feeding the redesign loop").

One India week (Monday 00:00 IST to the next Monday) of the rows Admin's overview reads
(telemetry/admin_view.py), compared with the week before:

- Screens: views, people, how long each is seen (visible time), quick backs (in and straight
  out again), back-and-forth loops, exits, rage and dead taps (with the element and zone),
  and taps on key actions that changed nothing.
- Flows (telemetry-flows.ts): first-run setup, phone setup, adding a lead and logging a
  call's result. How many start, the step each reaches, where they stop, refused Saves and
  the time to finish.
- Permission prompts in phone setup: granted, denied, blocked and how long the answer took.
- Workspace switching, read from the workspace each event was recorded in: switches,
  bounces (straight back within two minutes), ping-pong and switching right after opening.
- Findings ranked by people affected times severity, each with its evidence, the week
  before, a suggested owner and the question the builder should answer.

Counts, timings and code names only. No person, workspace or call is named or listed, and a
count of people under three is shown as "<3" so nobody can be singled out. The report is
computed from the stored events whenever it is asked for: a past week always reads the
same. The design is in docs/product/telemetry-friction-lab.md.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from ac_platform.telemetry.admin_view import Row
from ac_platform.telemetry.improvement import OWNERS, SCREEN_LABELS, SEVERITY_WORDS

SCHEMA = "ac.sales-xray.telemetry-friction/1"
INDIA = ZoneInfo("Asia/Kolkata")
WEEK = timedelta(days=7)
# Fewer people than this are shown as "<3" and never make a finding of their own.
MIN_PEOPLE = 3
# A screen left by Back within this long after arriving: a quick back.
QUICK_BACK_MS = 5_000
# Two screens visited A, B, A, B within this long: a back-and-forth loop.
LOOP_MS = 120_000
# Events further apart than this belong to different visits.
VISIT_GAP = timedelta(minutes=30)
# A switch straight back to the workspace before, within this long: a bounce.
BOUNCE = timedelta(minutes=2)
# Three or more switches within this long: ping-pong.
PING_PONG = timedelta(minutes=10)
PING_PONG_SWITCHES = 3
# A switch this soon after a visit started: they landed in the wrong workspace.
EARLY_SWITCH = timedelta(seconds=60)
# Opening the workspace menu without switching within this long: hesitation.
MENU_WAIT = timedelta(seconds=60)

FLOW_LABELS: Mapping[str, str] = {
    "onboarding": "First-run setup",
    "phone_setup": "Phone setup",
    "add_lead": "Add a lead",
    "log_result": "Log a call's result",
}
# Each flow's steps in the order its screens ask them (telemetry-flows.ts).
FLOW_ORDER: Mapping[str, tuple[str, ...]] = {
    "onboarding": ("start", "name", "business", "team", "first"),
    "phone_setup": (
        "calls",
        "notifications",
        "recordings",
        "battery",
        "autostart",
        "call_log",
        "recorder",
    ),
    "add_lead": ("form", "duplicate", "save"),
    "log_result": ("talk", "reason", "stage", "next", "save"),
}
STEP_LABELS: Mapping[str, str] = {
    "start": "How will you use it",
    "name": "Business name",
    "business": "What you sell",
    "team": "Invite your team",
    "first": "First lead or call",
    "calls": "Calls permission",
    "notifications": "Notifications",
    "recordings": "Call recordings",
    "battery": "Battery setting",
    "autostart": "Autostart",
    "call_log": "Call history",
    "recorder": "Call recorder",
    "form": "Name and number",
    "duplicate": "Already a lead",
    "save": "Save",
    "talk": "Did you talk?",
    "reason": "What happened",
    "stage": "What happens next",
    "next": "When to call next",
}
PERMISSION_LABELS: Mapping[str, str] = {
    "calls": "Calls",
    "notifications": "Notifications",
    "rec_files": "Call recordings",
    "all_files": "All files access",
    "folder": "Recordings folder",
    "battery": "Battery (unrestricted)",
    "autostart": "Autostart",
    "call_log": "Call history",
    "recorder": "Call recorder",
}
# The permissions without which calls aren't logged or recorded.
CORE_PERMISSIONS = frozenset({"calls", "rec_files", "all_files", "folder", "call_log"})
# Key actions whose "no change in a second" reads as a tap that did nothing.
KEY_ACTIONS = ("lead_open", "call_start", "outcome_save", "report_open", "sheet_open", "save")
QUIT = ("cancel", "abandon", "no_end")
QUESTIONS: Mapping[str, str] = {
    "rage_tap": "What did they expect this to do, and why didn't it answer at once?",
    "dead_tap": "It looks tappable: make it do what they expect, or stop it looking tappable.",
    "unresponsive": "The tap changed nothing for a second: show at once that it was taken.",
    "quick_back": "They open it and leave at once: is it the wrong place, or empty, or slow?",
    "loop": "They go back and forth between two screens: what are they comparing or looking "
    "for that one screen should show?",
    "flow_quit": "Why stop here: unclear words, a step they can't do yet, or too much asked?",
    "flow_blocked": "Save was refused for something missing: show what's missing before "
    "they tap, or ask less.",
    "permission": "Is the reason to allow clear before Android's prompt, and is the way back "
    "from settings obvious?",
    "workspace_bounce": "They switch and come straight back: do they know which workspace "
    "they are in and what each holds?",
    "error_shown": "What went wrong for them, and what does the message tell them to do?",
}


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_window(start: date) -> tuple[datetime, datetime]:
    """The India week that starts on this Monday, in UTC."""
    begin = datetime.combine(monday(start), time(0, 0), tzinfo=INDIA)
    return begin.astimezone(UTC), (begin + WEEK).astimezone(UTC)


def last_full_week(now: datetime) -> date:
    """The Monday of the last India week that has ended."""
    return monday(now.astimezone(INDIA).date()) - WEEK


def _percentile(values: Sequence[float], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(share * len(ordered)) - 1)])


def _share(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def _number(payload: Mapping[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def people_count(count: int) -> int | str:
    """A count of people, or "<3" when it could single someone out."""
    return count if count >= MIN_PEOPLE or count == 0 else f"<{MIN_PEOPLE}"


def _screen(screen: str) -> str:
    return SCREEN_LABELS.get(screen, screen.replace("_", " "))


def _visit_key(row: Row) -> str:
    return row.session or f"{row.person}:{row.at.astimezone(INDIA).date().isoformat()}"


def _visits(rows: Iterable[Row]) -> dict[str, list[Row]]:
    """Each visit's events in time order: a session, split where it was idle 30 minutes."""
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[_visit_key(row)].append(row)
    visits: dict[str, list[Row]] = {}
    for key, items in grouped.items():
        items.sort(key=lambda row: row.at)
        part, start = 0, 0
        for index in range(1, len(items) + 1):
            if index == len(items) or items[index].at - items[index - 1].at > VISIT_GAP:
                visits[f"{key}#{part}"] = items[start:index]
                part, start = part + 1, index
    return visits


# ---------- screens ----------


@dataclass
class _Screen:
    views: int = 0
    people: set[str] = field(default_factory=set)
    seen: list[float] = field(default_factory=list)
    quick_backs: int = 0
    quick_people: set[str] = field(default_factory=set)
    exits: int = 0
    rage: int = 0
    dead: int = 0
    unresponsive: int = 0
    loops: int = 0

    @property
    def friction(self) -> int:
        """Friction events, weighted: a rage tap 3, a dead or unanswered tap 2, others 1."""
        return self.rage * 3 + self.dead * 2 + self.unresponsive * 2 + self.quick_backs + self.loops


def _seen_ms(row: Row) -> float | None:
    return _number(row.payload, "seen_ms") or _number(row.payload, "stay_ms")


def _loops(visit: Sequence[Row]) -> list[tuple[str, str, str]]:
    """Back-and-forth between two screens (A, B, A, B within two minutes) in one visit."""
    views = [row for row in visit if row.event == "sx.screen_viewed"]
    found: list[tuple[str, str, str]] = []
    index = 0
    while index + 3 < len(views):
        a, b, c, d = (str(view.payload.get("screen", "other")) for view in views[index : index + 4])
        if (
            a == c
            and b == d
            and a != b
            and views[index + 3].at - views[index].at <= timedelta(milliseconds=LOOP_MS)
        ):
            first, second = sorted((a, b))
            found.append((first, second, views[index].person))
            index += 3
        else:
            index += 1
    return found


def screens(rows: Sequence[Row], visits: Mapping[str, Sequence[Row]]) -> dict[str, Any]:
    table: dict[str, _Screen] = defaultdict(_Screen)
    elements: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
    for row in rows:
        payload = row.payload
        if row.event == "sx.screen_viewed":
            item = table[str(payload.get("screen", "other"))]
            item.views += 1
            item.people.add(row.person)
            source = str(payload.get("from", "none"))
            if source != "none" and (seen := _seen_ms(row)) is not None:
                before = table[source]
                before.seen.append(seen)
                if payload.get("nav") == "back" and seen < QUICK_BACK_MS:
                    before.quick_backs += 1
                    before.quick_people.add(row.person)
        elif row.event == "sx.screen_hidden":
            item = table[str(payload.get("screen", "other"))]
            if (seen := _number(payload, "seen_ms")) is not None:
                item.seen.append(seen)
            if payload.get("kind") == "exit":
                item.exits += 1
        elif row.event == "sx.tap_issue":
            screen = str(payload.get("screen", "other"))
            kind = str(payload.get("kind", ""))
            if kind == "rage":
                table[screen].rage += 1
            elif kind == "dead":
                table[screen].dead += 1
            else:
                continue
            element = str(payload.get("element") or payload.get("target") or "other")
            elements[(kind, screen, element)].append(row)
        elif (
            row.event == "sx.action_timing"
            and payload.get("result") == "no_change"
            and payload.get("action") in KEY_ACTIONS
        ):
            table[str(payload.get("screen", "other"))].unresponsive += 1
    # The last screen of a visit that never said it closed counts as where it ended.
    for visit in visits.values():
        views = [row for row in visit if row.event == "sx.screen_viewed"]
        if views and not any(
            row.event == "sx.screen_hidden" and row.payload.get("kind") == "exit" for row in visit
        ):
            table[str(views[-1].payload.get("screen", "other"))].exits += 1
    loop_people: dict[tuple[str, str], set[str]] = defaultdict(set)
    loop_count: Counter[tuple[str, str]] = Counter()
    for visit in visits.values():
        for first, second, person in _loops(visit):
            loop_people[(first, second)].add(person)
            loop_count[(first, second)] += 1
            table[first].loops += 1
            table[second].loops += 1

    def per_100(count: int, views: int) -> float | None:
        return round(count * 100 / views, 1) if views else None

    listed = [
        {
            "screen": name,
            "label": _screen(name),
            "views": item.views,
            "people": people_count(len(item.people)),
            "seen_p50_ms": _percentile(item.seen, 0.5),
            "seen_p90_ms": _percentile(item.seen, 0.9),
            "quick_back_share": _share(item.quick_backs, item.views),
            "exit_share": _share(item.exits, item.views),
            "rage_per_100": per_100(item.rage, item.views),
            "dead_per_100": per_100(item.dead, item.views),
            "unresponsive": item.unresponsive,
            "loops": item.loops,
            # One number to sort screens by: weighted friction events per 100 views.
            "friction_per_100": per_100(item.friction, item.views),
        }
        for name, item in table.items()
    ]
    listed.sort(key=lambda item: (-(item["friction_per_100"] or 0), -item["views"]))
    return {
        "screens": listed,
        "elements": elements,
        "loops": [
            {
                "screens": list(pair),
                "labels": [_screen(name) for name in pair],
                "count": loop_count[pair],
                "people": people_count(len(people)),
                "people_n": len(people),
            }
            for pair, people in sorted(loop_people.items(), key=lambda item: -len(item[1]))
        ],
        "quick": {name: item.quick_people for name, item in table.items()},
        "views": {name: item.views for name, item in table.items()},
        "quick_backs": {name: item.quick_backs for name, item in table.items()},
    }


# ---------- flows ----------


@dataclass
class _Run:
    flow: str
    person: str
    via: str | None
    started: datetime
    steps: list[str]
    blocked: Counter[str]
    end: str = "no_end"
    end_step: str | None = None
    ms: float | None = None
    left: float | None = None


def _runs(visits: Mapping[str, Sequence[Row]]) -> list[_Run]:
    """Each flow run: from its start to how it ended ("no_end" when nothing said)."""
    runs: list[_Run] = []
    for visit in visits.values():
        open_runs: dict[str, _Run] = {}
        for row in visit:
            if row.event != "sx.flow":
                continue
            payload = row.payload
            flow = str(payload.get("flow", ""))
            outcome = str(payload.get("outcome", ""))
            step = payload.get("step")
            current = open_runs.get(flow)
            if outcome == "start" or current is None:
                if current is not None:
                    runs.append(current)
                via = payload.get("via")
                current = _Run(
                    flow=flow,
                    person=row.person,
                    via=str(via) if via else None,
                    started=row.at,
                    steps=[],
                    blocked=Counter(),
                )
                open_runs[flow] = current
            if isinstance(step, str) and (not current.steps or current.steps[-1] != step):
                current.steps.append(step)
            if outcome == "blocked" and isinstance(step, str):
                current.blocked[step] += 1
            if outcome in ("done", "skip", "cancel", "abandon", "fail"):
                current.end = outcome
                current.end_step = (
                    step
                    if isinstance(step, str)
                    else (current.steps[-1] if current.steps else None)
                )
                current.ms = _number(payload, "ms")
                current.left = _number(payload, "left")
                runs.append(current)
                del open_runs[flow]
        runs.extend(open_runs.values())
    for run in runs:
        if run.end == "no_end" and run.steps:
            run.end_step = run.steps[-1]
    return runs


def flows(runs: Sequence[_Run]) -> list[dict[str, Any]]:
    listed = []
    for flow, label in FLOW_LABELS.items():
        mine = [run for run in runs if run.flow == flow]
        if not mine:
            continue
        ends = Counter(run.end for run in mine)
        order = list(FLOW_ORDER[flow])
        order += sorted({step for run in mine for step in run.steps} - set(order))
        steps = []
        for step in order:
            reached = [run for run in mine if step in run.steps]
            if not reached:
                continue
            quit_here = [run for run in mine if run.end in QUIT and run.end_step == step]
            blocked = sum(run.blocked[step] for run in mine)
            steps.append(
                {
                    "step": step,
                    "label": STEP_LABELS.get(step, step),
                    "reached": len(reached),
                    "reached_share": _share(len(reached), len(mine)),
                    "quit": len(quit_here),
                    "quit_people": people_count(len({run.person for run in quit_here})),
                    "quit_people_n": len({run.person for run in quit_here}),
                    "blocked": blocked,
                    "blocked_people_n": len({run.person for run in mine if run.blocked[step]}),
                }
            )
        done = [run for run in mine if run.end == "done"]
        times = [run.ms for run in done if run.ms is not None]
        lefts = [run.left for run in done if run.left is not None]
        worst = max(steps, key=lambda item: (item["quit"], -item["reached"]), default=None)
        listed.append(
            {
                "flow": flow,
                "label": label,
                "started": len(mine),
                "people": people_count(len({run.person for run in mine})),
                "done": ends["done"],
                "skipped": ends["skip"],
                "cancelled": ends["cancel"],
                "abandoned": ends["abandon"],
                "no_end": ends["no_end"],
                "failed": ends["fail"],
                "done_share": _share(ends["done"], len(mine)),
                "quit_share": _share(sum(ends[end] for end in QUIT), len(mine)),
                "done_p50_ms": _percentile(times, 0.5),
                "done_p90_ms": _percentile(times, 0.9),
                # Phone setup: what was still left when it ended.
                "left_after_done": round(median(lefts), 1) if lefts else None,
                "vias": dict(Counter(run.via or "unknown" for run in mine)),
                "steps": steps,
                "worst_step": worst["step"] if worst and worst["quit"] else None,
            }
        )
    return listed


# ---------- permission prompts ----------


def permissions(rows: Sequence[Row]) -> list[dict[str, Any]]:
    asked: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        if row.event == "sx.permission_prompt":
            asked[str(row.payload.get("permission", "other"))].append(row)
    listed = []
    for permission, items in asked.items():
        outcomes = Counter(str(row.payload.get("outcome", "unknown")) for row in items)
        answered = outcomes["granted"] + outcomes["denied"] + outcomes["blocked"]
        times = [value for row in items if (value := _number(row.payload, "ms")) is not None]
        refused = [row for row in items if row.payload.get("outcome") in ("denied", "blocked")]
        listed.append(
            {
                "permission": permission,
                "label": PERMISSION_LABELS.get(permission, permission),
                "asked": len(items),
                "people": people_count(len({row.person for row in items})),
                "granted": outcomes["granted"],
                "denied": outcomes["denied"],
                "blocked": outcomes["blocked"],
                "not_opened": outcomes["not_opened"],
                "unknown": outcomes["unknown"],
                "granted_share": _share(outcomes["granted"], answered),
                "refused_people_n": len({row.person for row in refused}),
                "answer_p50_ms": _percentile(times, 0.5),
                "settings_share": _share(
                    sum(1 for row in items if row.payload.get("via") == "settings"), len(items)
                ),
                "core": permission in CORE_PERMISSIONS,
            }
        )
    listed.sort(key=lambda item: (-item["asked"], item["permission"]))
    return listed


# ---------- workspace switching ----------


def workspaces(rows: Sequence[Row], kinds: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Switches read from the workspace each event was recorded in, per person. ``kinds``
    names Personal and the operations workspace by id; any other is an organisation."""
    kinds = kinds or {}
    other = "organisation" if kinds else "workspace"
    by_person: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_person[row.person].append(row)
    switches = bounces = early = 0
    multi: set[str] = set()
    switchers: set[str] = set()
    bouncers: set[str] = set()
    ping_pong: set[str] = set()
    early_people: set[str] = set()
    directions: Counter[str] = Counter()
    menu_opens = menu_left = 0
    for person, items in by_person.items():
        items.sort(key=lambda row: row.at)
        if len({row.workspace for row in items}) > 1:
            multi.add(person)
        moves: list[tuple[datetime, str, str]] = []
        visit_start = items[0].at
        for before, after in zip(items, items[1:], strict=False):
            if after.at - before.at > VISIT_GAP:
                visit_start = after.at
            if after.workspace == before.workspace or after.at - before.at > VISIT_GAP:
                continue
            moves.append((after.at, before.workspace, after.workspace))
            if after.at - visit_start <= EARLY_SWITCH:
                early += 1
                early_people.add(person)
        for _, source, target in moves:
            directions[f"{kinds.get(source, other)}_to_{kinds.get(target, other)}"] += 1
        switches += len(moves)
        if moves:
            switchers.add(person)
        for (at, source, target), (later, back_from, back_to) in zip(
            moves, moves[1:], strict=False
        ):
            if back_from == target and back_to == source and later - at <= BOUNCE:
                bounces += 1
                bouncers.add(person)
        for index in range(len(moves) - PING_PONG_SWITCHES + 1):
            if moves[index + PING_PONG_SWITCHES - 1][0] - moves[index][0] <= PING_PONG:
                ping_pong.add(person)
                break
        opens = [
            row.at
            for row in items
            if row.event == "sx.feature_used" and row.payload.get("feature") == "workspace_menu"
        ]
        menu_opens += len(opens)
        menu_left += sum(
            1
            for opened in opens
            if not any(opened <= at <= opened + MENU_WAIT for at, _, _ in moves)
        )
    return {
        "people": people_count(len(by_person)),
        "people_in_several": people_count(len(multi)),
        "switches": switches,
        "switch_people": people_count(len(switchers)),
        "bounces": bounces,
        "bounce_people": people_count(len(bouncers)),
        "bounce_people_n": len(bouncers),
        "ping_pong_people": people_count(len(ping_pong)),
        "ping_pong_people_n": len(ping_pong),
        "early_switches": early,
        "early_people": people_count(len(early_people)),
        "early_people_n": len(early_people),
        "directions": dict(directions.most_common()),
        "menu_opens": menu_opens,
        "menu_left": menu_left,
    }


# ---------- findings ----------


@dataclass(frozen=True)
class Finding:
    key: str
    kind: str
    title: str
    screen: str
    severity: int
    people: int
    events: int
    evidence: Mapping[str, Any]
    # Who is suggested where the screen alone doesn't say (a flow's owner).
    owner: str | None = None

    @property
    def score(self) -> int:
        return self.people * self.severity


# The sessions that own each flow (25 Oct 2026); a suggestion, the orchestrator assigns.
FLOW_OWNERS: Mapping[str, str] = {
    "onboarding": "Builder (sign-in and first-run setup)",
    "phone_setup": "Android app and phone setup",
    "add_lead": "Lead OS",
    "log_result": "Lead OS",
}
FLOW_SCREENS: Mapping[str, str] = {
    "onboarding": "welcome",
    "phone_setup": "android_app",
    "add_lead": "leads",
    "log_result": "lead",
}


def _element_words(element: str, target: str) -> str:
    return f"`{element}`" if element and element != target else f"a {target}"


def findings(
    rows: Sequence[Row],
    screen_part: Mapping[str, Any],
    flow_part: Sequence[Mapping[str, Any]],
    permission_part: Sequence[Mapping[str, Any]],
    workspace_part: Mapping[str, Any],
) -> list[Finding]:
    found: list[Finding] = []
    # Rage and dead taps, per screen and element.
    for (kind, screen, element), items in screen_part["elements"].items():
        people = len({row.person for row in items})
        if people < MIN_PEOPLE:
            continue
        target = Counter(str(row.payload.get("target", "other")) for row in items).most_common(1)
        zones = Counter(str(row.payload["zone"]) for row in items if row.payload.get("zone"))
        what = _element_words(element, target[0][0] if target else "other")
        found.append(
            Finding(
                key=f"{kind}:{screen}:{element}",
                kind=f"{kind}_tap",
                title=(
                    f"Repeated taps on {what} on {_screen(screen)}"
                    if kind == "rage"
                    else f"Taps on {what} that does nothing on {_screen(screen)}"
                ),
                screen=screen,
                severity=3 if kind == "rage" else 2,
                people=people,
                events=len(items),
                evidence={
                    "taps": len(items),
                    "element": element,
                    "target": target[0][0] if target else "other",
                    "zones": [zone for zone, _ in zones.most_common(2)],
                    "views": screen_part["views"].get(screen, 0),
                },
            )
        )
    # Key actions whose tap changed nothing for a second.
    unresponsive: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        if (
            row.event == "sx.action_timing"
            and row.payload.get("result") == "no_change"
            and row.payload.get("action") in KEY_ACTIONS
        ):
            unresponsive[
                (str(row.payload.get("action")), str(row.payload.get("screen", "other")))
            ].append(row)
    for (action, screen), items in unresponsive.items():
        people = len({row.person for row in items})
        if people < MIN_PEOPLE:
            continue
        taps = sum(
            1
            for row in rows
            if row.event == "sx.action_timing"
            and row.payload.get("action") == action
            and row.payload.get("screen", "other") == screen
        )
        found.append(
            Finding(
                key=f"unresponsive:{action}:{screen}",
                kind="unresponsive",
                title=f"Taps on {action.replace('_', ' ')} change nothing at first on "
                f"{_screen(screen)}",
                screen=screen,
                severity=2,
                people=people,
                events=len(items),
                evidence={"no_change": len(items), "taps": taps, "share": _share(len(items), taps)},
            )
        )
    # Quick backs: in and straight out again.
    for screen, people in screen_part["quick"].items():
        views = screen_part["views"].get(screen, 0)
        backs = screen_part["quick_backs"].get(screen, 0)
        if len(people) < MIN_PEOPLE or views < 10 or (_share(backs, views) or 0) < 0.25:
            continue
        found.append(
            Finding(
                key=f"quick_back:{screen}",
                kind="quick_back",
                title=f"People open {_screen(screen)} and leave it within seconds",
                screen=screen,
                severity=2,
                people=len(people),
                events=backs,
                evidence={
                    "quick_backs": backs,
                    "views": views,
                    "share": _share(backs, views),
                    "within_ms": QUICK_BACK_MS,
                },
            )
        )
    # Back-and-forth loops between two screens.
    for loop in screen_part["loops"]:
        if loop["people_n"] < MIN_PEOPLE:
            continue
        first, second = loop["screens"]
        found.append(
            Finding(
                key=f"loop:{first}:{second}",
                kind="loop",
                title=f"Back and forth between {_screen(first)} and {_screen(second)}",
                screen=first,
                severity=2,
                people=loop["people_n"],
                events=loop["count"],
                evidence={"loops": loop["count"], "within_ms": LOOP_MS},
            )
        )
    # Where flows stop, and Saves refused for something missing.
    for flow in flow_part:
        name = flow["flow"]
        for step in flow["steps"]:
            if step["quit_people_n"] >= MIN_PEOPLE:
                found.append(
                    Finding(
                        key=f"flow_quit:{name}:{step['step']}",
                        kind="flow_quit",
                        title=f"{flow['label']}: people stop at “{step['label']}”",
                        screen=FLOW_SCREENS.get(name, "other"),
                        # Not finishing setup or not logging a call loses the person or the lead.
                        severity=4 if name in ("onboarding", "log_result") else 3,
                        people=step["quit_people_n"],
                        events=step["quit"],
                        evidence={
                            "started": flow["started"],
                            "reached": step["reached"],
                            "stopped_here": step["quit"],
                            "finished": _pct(flow["done_share"]),
                        },
                        owner=FLOW_OWNERS.get(name),
                    )
                )
            if step["blocked_people_n"] >= MIN_PEOPLE:
                found.append(
                    Finding(
                        key=f"flow_blocked:{name}:{step['step']}",
                        kind="flow_blocked",
                        title=f"{flow['label']}: Save refused at “{step['label']}”",
                        screen=FLOW_SCREENS.get(name, "other"),
                        severity=2,
                        people=step["blocked_people_n"],
                        events=step["blocked"],
                        evidence={"refused": step["blocked"], "reached": step["reached"]},
                        owner=FLOW_OWNERS.get(name),
                    )
                )
    # Permissions people refuse or Android no longer asks for.
    for item in permission_part:
        answered = item["granted"] + item["denied"] + item["blocked"]
        refused = item["denied"] + item["blocked"]
        if (
            item["refused_people_n"] < MIN_PEOPLE
            or answered < 4
            or (_share(refused, answered) or 0) < 0.25
        ):
            continue
        found.append(
            Finding(
                key=f"permission_prompt:{item['permission']}",
                kind="permission",
                title=f"People refuse {item['label']} in phone setup",
                screen="android_app",
                severity=3 if item["core"] else 2,
                people=item["refused_people_n"],
                events=refused,
                evidence={
                    "asked": item["asked"],
                    "denied": item["denied"],
                    "blocked": item["blocked"],
                    "granted_share": item["granted_share"],
                },
            )
        )
    # Switching workspace and coming straight back.
    if workspace_part["bounce_people_n"] >= MIN_PEOPLE:
        found.append(
            Finding(
                key="workspace:bounce",
                kind="workspace_bounce",
                title="People switch workspace and come straight back",
                screen="organisation",
                severity=3,
                people=workspace_part["bounce_people_n"],
                events=workspace_part["bounces"],
                evidence={
                    "bounces": workspace_part["bounces"],
                    "switches": workspace_part["switches"],
                    "ping_pong_people": workspace_part["ping_pong_people"],
                },
            )
        )
    if workspace_part["early_people_n"] >= MIN_PEOPLE:
        found.append(
            Finding(
                key="workspace:early",
                kind="workspace_bounce",
                title="People open the app in one workspace and switch within a minute",
                screen="organisation",
                severity=2,
                people=workspace_part["early_people_n"],
                events=workspace_part["early_switches"],
                evidence={
                    "early_switches": workspace_part["early_switches"],
                    "directions": workspace_part["directions"],
                },
            )
        )
    # Errors people were shown, per surface and code.
    shown: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        if row.event == "sx.error_shown":
            shown[(str(row.payload.get("surface")), str(row.payload.get("code")))].append(row)
    for (surface, code), items in shown.items():
        people = len({row.person for row in items})
        if people < MIN_PEOPLE:
            continue
        found.append(
            Finding(
                key=f"error_shown:{surface}:{code}",
                kind="error_shown",
                title=f"People see the error “{code.replace('_', ' ')}” on {surface}",
                screen=surface if surface in SCREEN_LABELS else "other",
                severity=2,
                people=people,
                events=len(items),
                evidence={"shown": len(items)},
            )
        )
    return found


# ---------- the report ----------


def _coverage(rows: Sequence[Row], visits: Mapping[str, Sequence[Row]]) -> dict[str, Any]:
    apps = Counter(str(row.payload.get("app", "web")) for row in rows)
    return {
        "events": len(rows),
        "people": people_count(len({row.person for row in rows})),
        "visits": len(visits),
        "days": len({row.at.astimezone(INDIA).date() for row in rows}),
        "apps": dict(apps),
        "releases": sorted({row.release for row in rows if row.release}),
        "flow_events": sum(1 for row in rows if row.event == "sx.flow"),
        "prompt_events": sum(1 for row in rows if row.event == "sx.permission_prompt"),
    }


def report(
    current: Sequence[Row],
    before: Sequence[Row],
    *,
    week: date,
    now: datetime,
    environment: str,
    kinds: Mapping[str, str] | None = None,
    truncated: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """One week's friction report, with each finding against the week before."""

    def parts(rows: Sequence[Row]) -> tuple[Any, ...]:
        visits = _visits(rows)
        runs = _runs(visits)
        screen_part = screens(rows, visits)
        flow_part = flows(runs)
        permission_part = permissions(rows)
        workspace_part = workspaces(rows, kinds)
        found = findings(rows, screen_part, flow_part, permission_part, workspace_part)
        return visits, screen_part, flow_part, permission_part, workspace_part, found

    visits, screen_part, flow_part, permission_part, workspace_part, found = parts(current)
    earlier = {item.key: item for item in parts(before)[5]} if before else {}
    ranked = sorted(found, key=lambda item: (-item.score, -item.events, item.key))
    start, end = week_window(week)
    items = []
    for rank, finding in enumerate(ranked[:limit], start=1):
        was = earlier.get(finding.key)
        items.append(
            {
                "rank": rank,
                "key": finding.key,
                "kind": finding.kind,
                "title": finding.title,
                "screen": finding.screen,
                "screen_label": _screen(finding.screen),
                "severity": finding.severity,
                "severity_label": SEVERITY_WORDS[finding.severity],
                "people": finding.people,
                "events": finding.events,
                "score": finding.score,
                "evidence": dict(finding.evidence),
                "people_before": was.people if was else None,
                "new": was is None,
                "owner": finding.owner or OWNERS.get(finding.screen, "Sales X-Ray web"),
                "question": QUESTIONS.get(finding.kind, ""),
            }
        )
    gone = [
        {"key": key, "title": item.title, "people_before": item.people}
        for key, item in earlier.items()
        if key not in {finding.key for finding in found}
    ]
    gone.sort(key=lambda item: -item["people_before"])
    return {
        "schema": SCHEMA,
        "environment": environment,
        "generated_at": now.isoformat(),
        "week": monday(week).isoformat(),
        "since": start.isoformat(),
        "until": min(end, now).isoformat(),
        "complete": now >= end,
        "truncated": truncated,
        "coverage": _coverage(current, visits),
        "findings": items,
        "more": max(0, len(ranked) - limit),
        "gone": gone[:10],
        "flows": flow_part,
        "permissions": permission_part,
        "workspaces": workspace_part,
        "screens": screen_part["screens"][:25],
        "loops": [
            {key: value for key, value in loop.items() if key != "people_n"}
            for loop in screen_part["loops"][:10]
        ],
        "thresholds": {
            "min_people": MIN_PEOPLE,
            "quick_back_ms": QUICK_BACK_MS,
            "loop_ms": LOOP_MS,
            "bounce_ms": int(BOUNCE.total_seconds() * 1000),
            "visit_gap_min": int(VISIT_GAP.total_seconds() // 60),
        },
    }


def _ms_words(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value / 1000:.1f} s" if value < 60_000 else f"{value / 60_000:.1f} min"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)}%"


def _cells(values: Iterable[Any]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _evidence_words(evidence: Mapping[str, Any]) -> str:
    def value_words(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(map(str, value))
        if isinstance(value, dict):
            return ", ".join(f"{key.replace('_', ' ')} {count}" for key, count in value.items())
        if isinstance(value, float) and value <= 1:
            return _pct(value)
        return str(value)

    return "; ".join(
        f"{key.replace('_', ' ')} {value_words(value)}"
        for key, value in evidence.items()
        if value not in (None, [], {})
    )


def to_markdown(data: Mapping[str, Any]) -> str:
    """The report as markdown for the owner and the builder (the weekly job writes it)."""
    start = datetime.fromisoformat(data["since"]).astimezone(INDIA)
    until = datetime.fromisoformat(data["until"]).astimezone(INDIA)
    coverage = data["coverage"]
    lines = [
        f"# Sales X-Ray friction report: week of {start:%d %b %Y}",
        "",
        f"{data['environment']} · {start:%a %d %b} to {until:%a %d %b %Y, %H:%M} IST"
        + ("" if data["complete"] else " (week still running)")
        + f" · made {datetime.fromisoformat(data['generated_at']).astimezone(INDIA):%d %b %H:%M}"
        " IST",
        "",
        f"Based on {coverage['events']} events from {coverage['people']} people in "
        f"{coverage['visits']} visits over {coverage['days']} days "
        f"({', '.join(f'{app} {count}' for app, count in coverage['apps'].items()) or 'no apps'})."
        + (
            " The read hit its row limit, so counts are a lower bound." if data["truncated"] else ""
        ),
        "",
        "Counts and timings only: nobody is named, and fewer than three people show as <3.",
        "",
        "## What to fix first",
        "",
    ]
    if not data["findings"]:
        lines.append(
            "Nothing reached the bar this week (three people or more). See the tables below."
        )
    for item in data["findings"]:
        before = (
            "new this week" if item["new"] else f"{item['people_before']} people the week before"
        )
        lines += [
            f"{item['rank']}. **{item['title']}** — {item['people']} people, "
            f"{item['events']} times · {item['severity_label'].lower()} · {before}",
            f"   - Evidence: {_evidence_words(item['evidence'])}.",
            f"   - Ask: {item['question']}",
            f"   - Screen: {item['screen_label']} · suggested owner: {item['owner']} · "
            f"finding `{item['key']}`",
        ]
    if data["more"]:
        lines.append(f"\n…and {data['more']} more in Admin → Product telemetry → Friction.")
    if data["gone"]:
        lines += [
            "",
            "**Gone since the week before:** "
            + "; ".join(
                f"{item['title']} ({item['people_before']} people)" for item in data["gone"]
            ),
        ]
    lines += ["", "## Flows: where people stop", ""]
    if not data["flows"]:
        lines.append("No flow events yet (they start with the release that carries them).")
    for flow in data["flows"]:
        lines += [
            f"**{flow['label']}**: {flow['started']} started by {flow['people']} people; "
            f"{_pct(flow['done_share'])} finished, {_pct(flow['quit_share'])} stopped "
            f"(cancelled {flow['cancelled']}, left half way {flow['abandoned']}, no end seen "
            f"{flow['no_end']}), skipped {flow['skipped']}, failed {flow['failed']}. "
            f"Time to finish: median {_ms_words(flow['done_p50_ms'])}, 90% within "
            f"{_ms_words(flow['done_p90_ms'])}.",
            "",
            "| Step | Reached | Stopped here | Save refused |",
            "|---|---|---|---|",
        ]
        lines += [
            _cells(
                (
                    step["label"],
                    f"{step['reached']} ({_pct(step['reached_share'])})",
                    step["quit"],
                    step["blocked"],
                )
            )
            for step in flow["steps"]
        ]
        lines.append("")
    lines += ["## Permission prompts (phone setup)", ""]
    if data["permissions"]:
        lines += [
            "| Permission | Asked | Granted | Denied | Blocked | Didn't open | Answer (median) |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [
            _cells(
                (
                    item["label"],
                    item["asked"],
                    f"{item['granted']} ({_pct(item['granted_share'])})",
                    item["denied"],
                    item["blocked"],
                    item["not_opened"],
                    _ms_words(item["answer_p50_ms"]),
                )
            )
            for item in data["permissions"]
        ]
    else:
        lines.append("No prompts recorded this week.")
    switching = data["workspaces"]
    lines += [
        "",
        "## Workspace switching",
        "",
        f"{switching['people_in_several']} people used more than one workspace; "
        f"{switching['switches']} switches by {switching['switch_people']} people. "
        f"Straight back within two minutes: {switching['bounces']} "
        f"({switching['bounce_people']} people). Three or more switches in ten minutes: "
        f"{switching['ping_pong_people']} people. Switched within a minute of opening: "
        f"{switching['early_switches']} ({switching['early_people']} people). "
        f"Workspace menu opened {switching['menu_opens']} times, "
        f"{switching['menu_left']} without a switch.",
        "",
        "## Screens by friction",
        "",
        "| Screen | Views | People | Seen (median / 90%) | Quick back | Exits | Rage /100 | "
        "Dead /100 | No change | Loops |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        _cells(
            (
                item["label"],
                item["views"],
                item["people"],
                f"{_ms_words(item['seen_p50_ms'])} / {_ms_words(item['seen_p90_ms'])}",
                _pct(item["quick_back_share"]),
                _pct(item["exit_share"]),
                item["rage_per_100"] if item["rage_per_100"] is not None else "–",
                item["dead_per_100"] if item["dead_per_100"] is not None else "–",
                item["unresponsive"],
                item["loops"],
            )
        )
        for item in data["screens"][:15]
    ]
    thresholds = data["thresholds"]
    lines += [
        "",
        "## How this is worked out",
        "",
        f"- A visit is one session, split where it was idle {thresholds['visit_gap_min']} "
        "minutes. Time on a screen counts only while the app was on screen.",
        f"- Quick back: a screen left with Back within {thresholds['quick_back_ms'] // 1000} s. "
        f"Loop: two screens visited A, B, A, B within {thresholds['loop_ms'] // 1000} s.",
        "- Flows end as done, skipped, cancelled, left half way (the screen closed) or with no "
        "end seen (the app was closed or killed). Save refused: tapped while something was "
        "missing.",
        f"- Workspace switches come from the workspace each event was recorded in; a bounce is "
        f"a switch straight back within {thresholds['bounce_ms'] // 60000} minutes.",
        f"- A finding needs {thresholds['min_people']} people or more. Rank = people × "
        "severity (1 minor to 4 critical).",
        "- Source: Admin → Product telemetry → Friction (the same numbers, live).",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "MIN_PEOPLE",
    "SCHEMA",
    "last_full_week",
    "monday",
    "people_count",
    "report",
    "to_markdown",
    "week_window",
]

"""The improvement loop over Sales X-Ray telemetry (owner, 24 Oct 2026: "where is the
telemetry data of each device ... I want it to be nicely visualised and presented and more
importantly use in our recursive improvement pipeline each new update we improve the app
using that data").

Four reads over the rows Admin's overview reads (telemetry/admin_view.py): counts, timings and
codes only. No person, workspace or call is named or listed, and sandboxes never record.

- devices(): every phone model and device class seen, with its app versions, Android and
  WebView versions, network and memory tier; per device, speed on the key actions, errors,
  crashes and rage and dead taps; and the slowest 10% of devices.
- compare(): one release against the one before it on key actions, errors and funnels.
- gate(): the release train's input. A key action that got slower beyond the threshold
  blocks promotion unless the owner overrides it.
- fix_next(): what to fix next, ranked by people affected times severity. Each finding has
  its evidence, screen, a suggested owner session, how it moved by release, and whether it
  improved on the window before.

The design is in docs/product/telemetry-improvement-loop.md.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

from ac_platform.telemetry.admin_view import (
    ACTION_LABELS,
    DEFAULT_SLOW_MS,
    SLOW_MS,
    VITAL_LIMITS,
    WINDOWS,
    Filters,
    Read,
    Row,
    funnels,
)

DEVICES_SCHEMA = "ac.sales-xray.telemetry-devices/1"
COMPARE_SCHEMA = "ac.sales-xray.telemetry-compare/1"
GATE_SCHEMA = "ac.sales-xray.telemetry-gate/1"
FIX_NEXT_SCHEMA = "ac.sales-xray.telemetry-fix-next/1"

# The actions people feel most (owner: "open lead, tab switch, call, Report").
KEY_ACTIONS = ("lead_open", "tab_switch", "call_start", "report_open")
# A device needs this many key-action taps before it is ranked by speed.
MIN_DEVICE_TAPS = 3
CRASHES = ("crash", "crash_native", "anr")
KILLS = ("low_memory", "excessive_resource")

# The release gate: a key action's 75th percentile at least 20% and 150 ms slower, with at
# least 20 taps in each release, blocks promotion (the owner can override it).
GATE_RATIO = 1.2
GATE_MS = 150
GATE_MIN_TAPS = 20
# Warnings, never blocks: a rate per 100 sessions 50% and one event higher, with 20 sessions
# each; a funnel's last step 10 points lower, with 20 people at its first step.
RATE_RATIO = 1.5
RATE_MIN_SESSIONS = 20
FUNNEL_DROP = 0.1
FUNNEL_MIN_PEOPLE = 20
THRESHOLDS: Mapping[str, Any] = {
    "block": (
        f"A key action's 75th percentile at least {round((GATE_RATIO - 1) * 100)}% and "
        f"{GATE_MS} ms slower than the release before, with {GATE_MIN_TAPS} taps or more in each."
    ),
    "warn": (
        "Any other measure clearly worse: error, crash and tap-issue rates per 100 sessions "
        f"{round((RATE_RATIO - 1) * 100)}% and one event higher ({RATE_MIN_SESSIONS} sessions "
        f"each), Web Vitals 20% slower, or a funnel's last step {round(FUNNEL_DROP * 100)} "
        "points lower."
    ),
    "gate_ratio": GATE_RATIO,
    "gate_ms": GATE_MS,
    "gate_min_taps": GATE_MIN_TAPS,
}

SCREEN_LABELS: Mapping[str, str] = {
    "home": "Home",
    "dashboard": "Dashboard",
    "analysis": "Analysis",
    "new_call": "New call",
    "calls_list": "Calls",
    "report": "Report",
    "calls": "Calls",
    "leads": "Leads",
    "lead": "A lead",
    "chats": "Chats",
    "coaching": "Coaching",
    "prospects": "Prospects",
    "prospect": "A prospect",
    "organisation": "Organisation",
    "org_insights": "Organisation insights",
    "org_invites": "Invites",
    "org_person": "A team member",
    "settings": "Settings",
    "settings_section": "Settings",
    "account": "Account",
    "billing": "Billing",
    "plans": "Plans",
    "apps": "Apps",
    "developers": "Developers",
    "review": "Review",
    "android_app": "the Android app",
    "other": "other screens",
}

# Who is suggested for a finding on each screen (the sessions that own those parts of the
# app, 24 Oct 2026). A suggestion: Align 3 or the orchestrator assigns the card.
OWNERS: Mapping[str, str] = {
    "leads": "Lead OS",
    "lead": "Lead OS",
    "prospects": "Lead OS",
    "prospect": "Lead OS",
    "report": "Report (Brain 4.0)",
    "analysis": "Report (Brain 4.0)",
    "calls_list": "Report (Brain 4.0)",
    "calls": "Report (Brain 4.0)",
    "new_call": "Report (Brain 4.0)",
    "coaching": "Report (Brain 4.0)",
    "chats": "Chats inbox",
    "settings": "Settings and Admin (admin-2)",
    "settings_section": "Settings and Admin (admin-2)",
    "account": "Settings and Admin (admin-2)",
    "apps": "Settings and Admin (admin-2)",
    "developers": "Settings and Admin (admin-2)",
    "billing": "Billing",
    "plans": "Billing",
    "organisation": "Organisations",
    "org_insights": "Organisations",
    "org_invites": "Organisations",
    "org_person": "Organisations",
    "android_app": "Android app",
}
DEFAULT_OWNER = "Sales X-Ray web"
SEVERITY_WORDS: Mapping[int, str] = {1: "Minor", 2: "Moderate", 3: "Serious", 4: "Critical"}


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


def _groups(rows: Iterable[Row], key: Callable[[Row], Any]) -> dict[Any, list[Row]]:
    grouped: dict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _ms(rows: Iterable[Row], key: str = "ms") -> list[float]:
    return [value for row in rows if (value := _number(row.payload, key)) is not None]


def _threshold(action: str) -> int:
    return SLOW_MS.get(action, DEFAULT_SLOW_MS)


def _timing(rows: Sequence[Row], action: str) -> dict[str, Any]:
    values = _ms(rows)
    limit = _threshold(action)
    return {
        "taps": len(values),
        "p50": _percentile(values, 0.5),
        "p75": _percentile(values, 0.75),
        "slow_share": _share(sum(1 for value in values if value > limit), len(values)),
    }


def _counted(values: Iterable[tuple[str, str]], limit: int = 4) -> list[dict[str, Any]]:
    """(value, person) pairs as the values with the most people."""
    people: dict[str, set[str]] = defaultdict(set)
    for value, person in values:
        people[value].add(person)
    return [
        {"value": value, "people": len(group)}
        for value, group in sorted(people.items(), key=lambda pair: (-len(pair[1]), pair[0]))[
            :limit
        ]
    ]


def _is_action(row: Row, actions: tuple[str, ...] = KEY_ACTIONS) -> bool:
    return row.event == "sx.action_timing" and row.payload.get("action") in actions


# ---------- devices ----------


def _profiles(rows: Sequence[Row]) -> dict[str, Mapping[str, Any]]:
    """Each person's newest phone profile (the Android app's daily sx.device_profile)."""
    newest: dict[str, Row] = {}
    for row in rows:
        if row.event == "sx.device_profile" and (
            row.person not in newest or row.at > newest[row.person].at
        ):
            newest[row.person] = row
    return {person: row.payload for person, row in newest.items()}


@dataclass(frozen=True)
class DeviceKey:
    """A phone model (the Android app says which), or else a device class, app and tier."""

    kind: str
    maker: str = ""
    model: str = ""
    app: str = ""
    device: str = ""
    tier: str = ""

    def key(self) -> str:
        if self.kind == "model":
            return f"model:{self.maker}:{self.model}"
        return f"class:{self.app}:{self.device}:{self.tier}"

    def fields(self) -> dict[str, str]:
        if self.kind == "model":
            return {"kind": "model", "maker": self.maker, "model": self.model}
        return {"kind": "class", "app": self.app, "device": self.device, "tier": self.tier}


def _device_of(row: Row, profiles: Mapping[str, Mapping[str, Any]]) -> DeviceKey:
    payload = row.payload
    profile = profiles.get(row.person)
    if payload.get("app") == "android" and profile and (profile.get("model_label")):
        return DeviceKey(
            kind="model",
            maker=str(profile.get("maker", "unknown")),
            model=str(profile.get("model_label")),
        )
    return DeviceKey(
        kind="class",
        app=str(payload.get("app", "web")),
        device=str(payload.get("device", "unknown")),
        tier=str(payload.get("tier", "unknown")),
    )


def _slow_tail(taps: Sequence[Row]) -> set[int]:
    """The slowest tenth of each key action's taps (by position in ``taps``)."""
    tail: set[int] = set()
    by_action: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for index, row in enumerate(taps):
        value = _number(row.payload, "ms")
        if value is not None:
            by_action[str(row.payload.get("action"))].append((value, index))
    for items in by_action.values():
        items.sort(reverse=True)
        tail.update(index for _, index in items[: math.ceil(len(items) * 0.1)])
    return tail


def _index(rows: Sequence[Row]) -> float | None:
    """A device's speed: the median of its key-action taps' times over each action's limit
    (1.0 is a typical tap exactly at "slow")."""
    ratios = [
        value / _threshold(str(row.payload.get("action")))
        for row in rows
        if (value := _number(row.payload, "ms")) is not None
    ]
    return round(median(ratios), 3) if len(ratios) >= MIN_DEVICE_TAPS else None


def _issues(rows: Sequence[Row]) -> dict[str, int]:
    exits = [row for row in rows if row.event == "sx.app_exit"]
    return {
        "script_errors": sum(1 for row in rows if row.event == "sx.js_error"),
        "errors_shown": sum(1 for row in rows if row.event == "sx.error_shown"),
        "failed_calls": sum(
            1 for row in rows if row.event == "sx.api_slow" and row.payload.get("status") == "5xx"
        ),
        "crashes": sum(1 for row in exits if row.payload.get("reason") in CRASHES),
        "killed": sum(1 for row in exits if row.payload.get("reason") in KILLS),
        "rage_taps": sum(
            1 for row in rows if row.event == "sx.tap_issue" and row.payload.get("kind") == "rage"
        ),
        "dead_taps": sum(
            1 for row in rows if row.event == "sx.tap_issue" and row.payload.get("kind") == "dead"
        ),
    }


def _actions(taps: Sequence[Row]) -> dict[str, dict[str, Any]]:
    by_action = _groups(taps, lambda row: str(row.payload.get("action")))
    return {
        action: _timing(by_action[action], action) for action in KEY_ACTIONS if action in by_action
    }


def devices(read: Read, *, now: datetime, window: str, filters: Filters) -> dict[str, Any]:
    """Every device seen in the window: models and classes, their make-up, speed and issues,
    and the slowest 10% of devices (a device is one person's phone model or device class)."""
    rows = [row for row in read.rows if filters.keep(row)]
    profiles = _profiles(read.rows)
    keyed = [(row, _device_of(row, profiles)) for row in rows]
    taps = [row for row, _ in keyed if _is_action(row)]
    tail = _slow_tail(taps)
    tail_rows = {id(taps[index]) for index in tail}
    groups: dict[str, list[Row]] = defaultdict(list)
    keys: dict[str, DeviceKey] = {}
    units: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row, device in keyed:
        groups[device.key()].append(row)
        keys[device.key()] = device
        units[(row.person, device.key())].append(row)
    unit_index = {
        unit: _index([row for row in items if _is_action(row)]) for unit, items in units.items()
    }

    out: list[dict[str, Any]] = []
    for key, items in groups.items():
        device = keys[key]
        people = {row.person for row in items}
        group_taps = [row for row in items if _is_action(row)]
        indexes = [
            value
            for (_, unit_key), value in unit_index.items()
            if unit_key == key and value is not None
        ]
        out.append(
            {
                "key": key,
                **device.fields(),
                "people": len(people),
                "events": len(items),
                "app_versions": _counted(
                    (str(row.payload["app_version"]), row.person)
                    for row in items
                    if row.payload.get("app_version")
                ),
                "android": _counted(
                    (str(profile["android"]), person)
                    for person in people
                    if (profile := profiles.get(person)) and profile.get("android") is not None
                )
                if device.kind == "model"
                else [],
                "webview": _counted(
                    (str(profile["webview"]), person)
                    for person in people
                    if (profile := profiles.get(person)) and profile.get("webview")
                )
                if device.kind == "model"
                else [],
                "ram": _counted(
                    (str(profile["ram_tier"]), person)
                    for person in people
                    if (profile := profiles.get(person)) and profile.get("ram_tier")
                )
                if device.kind == "model"
                else [],
                "tiers": _counted(
                    (str(row.payload.get("tier", "unknown")), row.person) for row in items
                ),
                "networks": _counted(
                    (str(row.payload["net"]), row.person) for row in items if row.payload.get("net")
                ),
                "actions": _actions(group_taps),
                "taps": len(group_taps),
                "slow_tail_taps": sum(1 for row in group_taps if id(row) in tail_rows),
                "slow_tail_share": _share(
                    sum(1 for row in group_taps if id(row) in tail_rows), len(group_taps)
                ),
                "speed_index": round(median(indexes), 3) if indexes else None,
                **_issues(items),
            }
        )
    out.sort(key=lambda item: (-item["people"], -item["taps"], item["key"]))

    ranked = sorted(
        ((unit, value) for unit, value in unit_index.items() if value is not None),
        key=lambda pair: -pair[1],
    )
    cut = math.ceil(len(ranked) * 0.1)
    slowest = []
    for (person, key), value in ranked[:cut]:
        items = units[(person, key)]
        unit_taps = [row for row in items if _is_action(row)]
        versions = Counter(str(row.payload.get("app_version", "")) for row in items)
        networks = Counter(
            str(row.payload.get("net", "")) for row in items if row.payload.get("net")
        )
        profile = profiles.get(person, {}) if keys[key].kind == "model" else {}
        slowest.append(
            {
                "key": key,
                **keys[key].fields(),
                "speed_index": value,
                "taps": len(unit_taps),
                "app_version": versions.most_common(1)[0][0] if versions else "",
                "android": profile.get("android"),
                "ram": profile.get("ram_tier"),
                "network": networks.most_common(1)[0][0] if networks else None,
                "actions": _actions(unit_taps),
                **_issues(items),
            }
        )
    ranked_values = [value for _, value in ranked]
    return {
        "schema": DEVICES_SCHEMA,
        "generated_at": now.isoformat(),
        "window": window,
        "key_actions": [
            {
                "action": action,
                "label": ACTION_LABELS.get(action, action),
                "slow_ms": _threshold(action),
            }
            for action in KEY_ACTIONS
        ],
        "totals": {
            "devices": len(units),
            "ranked": len(ranked),
            "models": sum(1 for item in out if item["kind"] == "model"),
            "classes": sum(1 for item in out if item["kind"] == "class"),
            "slow_devices": sum(1 for value in ranked_values if value > 1),
            "slow_share": _share(
                sum(1 for value in ranked_values if value > 1), len(ranked_values)
            ),
        },
        "groups": out,
        "slowest": {
            "devices": slowest,
            "cutoff_index": slowest[-1]["speed_index"] if slowest else None,
            "median_index": round(median(ranked_values), 3) if ranked_values else None,
        },
    }


# ---------- releases ----------


def _sessions(rows: Sequence[Row]) -> int:
    return len({row.session or f"person:{row.person}" for row in rows})


def release_order(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Releases by when each was first seen, with how much each recorded."""
    out = []
    for release, items in _groups(
        [row for row in rows if row.release], lambda r: r.release
    ).items():
        out.append(
            {
                "release": release,
                "first_at": min(row.at for row in items),
                "events": len(items),
                "sessions": _sessions(items),
                "taps": sum(1 for row in items if _is_action(row)),
            }
        )
    out.sort(key=lambda item: item["first_at"])
    return out


def _funnel_last(rows: Sequence[Row]) -> list[tuple[str, str, int, float | None]]:
    out = []
    for funnel in funnels(rows):
        steps = funnel["steps"]
        if steps:
            out.append((funnel["key"], funnel["label"], steps[0]["people"], steps[-1]["share"]))
    return out


RATES: tuple[tuple[str, str, Callable[[Row], bool]], ...] = (
    ("script_errors", "Script errors", lambda r: r.event == "sx.js_error"),
    ("errors_shown", "Errors shown", lambda r: r.event == "sx.error_shown"),
    (
        "failed_calls",
        "Failed server calls",
        lambda r: r.event == "sx.api_slow" and r.payload.get("status") == "5xx",
    ),
    ("slow_calls", "Slow server calls", lambda r: r.event == "sx.api_slow"),
    (
        "rage_taps",
        "Rage taps",
        lambda r: r.event == "sx.tap_issue" and r.payload.get("kind") == "rage",
    ),
    (
        "dead_taps",
        "Dead taps",
        lambda r: r.event == "sx.tap_issue" and r.payload.get("kind") == "dead",
    ),
    (
        "crashes",
        "App crashes and freezes",
        lambda r: r.event == "sx.app_exit" and r.payload.get("reason") in CRASHES,
    ),
)


def _change(base: float | None, head: float | None) -> float | None:
    if base is None or head is None or base == 0:
        return None
    return round(head / base - 1, 4)


def _metrics(base_rows: Sequence[Row], head_rows: Sequence[Row]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for action in KEY_ACTIONS:
        old = _timing([row for row in base_rows if _is_action(row, (action,))], action)
        new = _timing([row for row in head_rows if _is_action(row, (action,))], action)
        enough = old["taps"] >= GATE_MIN_TAPS and new["taps"] >= GATE_MIN_TAPS
        verdict = "too_few"
        regression = False
        if enough and old["p75"] is not None and new["p75"] is not None:
            slower = new["p75"] - old["p75"]
            regression = new["p75"] >= old["p75"] * GATE_RATIO and slower >= GATE_MS
            verdict = (
                "worse"
                if regression or (slower >= 50 and new["p75"] >= old["p75"] * 1.1)
                else "better"
                if -slower >= 50 and old["p75"] >= new["p75"] * 1.1
                else "same"
            )
        out.append(
            {
                "key": f"speed:{action}",
                "kind": "speed",
                "label": ACTION_LABELS.get(action, action),
                "unit": "ms",
                "base": old["p75"],
                "head": new["p75"],
                "base_samples": old["taps"],
                "head_samples": new["taps"],
                "change": _change(old["p75"], new["p75"]),
                "verdict": verdict,
                "regression": regression,
                "slow_share": {"base": old["slow_share"], "head": new["slow_share"]},
            }
        )
    base_sessions, head_sessions = _sessions(base_rows), _sessions(head_rows)
    for key, label, test in RATES:
        old_count = sum(1 for row in base_rows if test(row))
        new_count = sum(1 for row in head_rows if test(row))
        old_rate = round(old_count * 100 / base_sessions, 2) if base_sessions else None
        new_rate = round(new_count * 100 / head_sessions, 2) if head_sessions else None
        enough = base_sessions >= RATE_MIN_SESSIONS and head_sessions >= RATE_MIN_SESSIONS
        verdict = "too_few"
        if enough and old_rate is not None and new_rate is not None:
            verdict = (
                "worse"
                if new_rate >= max(old_rate * RATE_RATIO, old_rate + 1)
                else "better"
                if old_rate >= max(new_rate * RATE_RATIO, new_rate + 1)
                else "same"
            )
        out.append(
            {
                "key": f"rate:{key}",
                "kind": "rate",
                "label": label,
                "unit": "per_100_sessions",
                "base": old_rate,
                "head": new_rate,
                "base_samples": base_sessions,
                "head_samples": head_sessions,
                "change": _change(old_rate, new_rate),
                "verdict": verdict,
                "regression": False,
            }
        )
    for metric in ("lcp", "inp"):
        old_values = _ms(
            (
                r
                for r in base_rows
                if r.event == "sx.web_vital" and r.payload.get("metric") == metric
            ),
            "value",
        )
        new_values = _ms(
            (
                r
                for r in head_rows
                if r.event == "sx.web_vital" and r.payload.get("metric") == metric
            ),
            "value",
        )
        old_p75, new_p75 = _percentile(old_values, 0.75), _percentile(new_values, 0.75)
        enough = len(old_values) >= GATE_MIN_TAPS and len(new_values) >= GATE_MIN_TAPS
        verdict = "too_few"
        if enough and old_p75 is not None and new_p75 is not None:
            verdict = (
                "worse"
                if new_p75 >= old_p75 * GATE_RATIO and new_p75 - old_p75 >= 50
                else "better"
                if old_p75 >= new_p75 * GATE_RATIO and old_p75 - new_p75 >= 50
                else "same"
            )
        out.append(
            {
                "key": f"vital:{metric}",
                "kind": "vital",
                "label": "Largest paint" if metric == "lcp" else "Tap to paint (INP)",
                "unit": "ms",
                "base": old_p75,
                "head": new_p75,
                "base_samples": len(old_values),
                "head_samples": len(new_values),
                "change": _change(old_p75, new_p75),
                "verdict": verdict,
                "regression": False,
            }
        )
    old_funnels = {key: (label, first, last) for key, label, first, last in _funnel_last(base_rows)}
    for key, label, first, last in _funnel_last(head_rows):
        _label, old_first, old_last = old_funnels.get(key, (label, 0, None))
        enough = old_first >= FUNNEL_MIN_PEOPLE and first >= FUNNEL_MIN_PEOPLE
        verdict = "too_few"
        if enough and old_last is not None and last is not None:
            verdict = (
                "worse"
                if old_last - last >= FUNNEL_DROP
                else "better"
                if last - old_last >= FUNNEL_DROP
                else "same"
            )
        out.append(
            {
                "key": f"funnel:{key}",
                "kind": "funnel",
                "label": label,
                "unit": "share",
                "base": old_last,
                "head": last,
                "base_samples": old_first,
                "head_samples": first,
                "change": None if old_last is None or last is None else round(last - old_last, 4),
                "verdict": verdict,
                "regression": False,
            }
        )
    return out


def _pick(
    order: Sequence[Mapping[str, Any]], head: str | None, base: str | None
) -> tuple[str | None, str | None]:
    names = [item["release"] for item in order]
    with_taps = [item["release"] for item in order if item["taps"]]
    head = (
        head if head in names else (with_taps[-1] if with_taps else (names[-1] if names else None))
    )
    if base not in names or base == head:
        earlier = names[: names.index(head)] if head in names else []
        candidates = [name for name in earlier if name in with_taps] or earlier
        base = candidates[-1] if candidates else None
    return head, base


def compare(
    read: Read,
    *,
    now: datetime,
    head: str | None = None,
    base: str | None = None,
    filters: Filters | None = None,
) -> dict[str, Any]:
    """A release against the one before it (or the two named): key actions, error rates per
    100 sessions, Web Vitals and funnels, each better, the same, worse or too few to say."""
    rows = [row for row in read.rows if (filters or Filters()).keep(row)]
    order = release_order(rows)
    head, base = _pick(order, head, base)
    by_release = _groups(rows, lambda row: row.release)
    metrics = _metrics(by_release.get(base or "", []), by_release.get(head or "", []))
    return {
        "schema": COMPARE_SCHEMA,
        "generated_at": now.isoformat(),
        "head": head,
        "base": base,
        "releases": [
            {**item, "first_at": item["first_at"].isoformat()} for item in reversed(order)
        ][:12],
        "metrics": metrics,
        "regressions": [item for item in metrics if item["regression"]],
        "worse": [item for item in metrics if item["verdict"] == "worse"],
        "better": [item for item in metrics if item["verdict"] == "better"],
        "thresholds": THRESHOLDS,
        "truncated": read.truncated,
    }


def gate(
    read: Read, *, now: datetime, environment: str, release: str, baseline: str | None = None
) -> dict[str, Any]:
    """The release train's input (Align 3): block when a key action regressed past the
    threshold; not_enough_data never blocks. The owner can override a block."""
    result = compare(read, now=now, head=release, base=baseline)
    known = result["head"] == release
    regressions = result["regressions"] if known else []
    sampled = (
        known
        and result["base"] is not None
        and any(
            item["verdict"] != "too_few" for item in result["metrics"] if item["kind"] == "speed"
        )
    )
    verdict = "block" if regressions else "pass" if sampled else "not_enough_data"
    reasons = [
        f"{item['label']}: 75th percentile {item['base']} ms → {item['head']} ms "
        f"({item['base_samples']} → {item['head_samples']} taps)"
        for item in regressions
    ]
    return {
        "schema": GATE_SCHEMA,
        "environment": environment,
        "generated_at": now.isoformat(),
        "release": release,
        "baseline": result["base"] if known else None,
        "verdict": verdict,
        "blocks_promotion": verdict == "block",
        "reasons": reasons,
        "warnings": [
            f"{item['label']}: {item['base']} → {item['head']}"
            for item in (result["worse"] if known else [])
            if not item["regression"]
        ],
        "override": "The owner can override a block; the release train records who and why.",
        "thresholds": THRESHOLDS,
        "metrics": result["metrics"] if known else [],
    }


# ---------- what to fix next ----------


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
    # The finding's measure on any rows (for its trend by release and the window before);
    # lower is better.
    measure: Callable[[Sequence[Row]], float | None]
    unit: str

    @property
    def score(self) -> int:
        return self.people * self.severity


def _screen_words(screen: str) -> str:
    return SCREEN_LABELS.get(screen, screen.replace("_", " "))


def _slow_measure(action: str, screen: str) -> Callable[[Sequence[Row]], float | None]:
    def measure(rows: Sequence[Row]) -> float | None:
        values = _ms(
            row
            for row in rows
            if _is_action(row, (action,)) and row.payload.get("screen", "other") == screen
        )
        return float(p75) if (p75 := _percentile(values, 0.75)) is not None else None

    return measure


def _match(event: str, **fields: str) -> Callable[[Row], bool]:
    """A row of this event whose payload has these values ("other" where a key is absent)."""

    def test(row: Row) -> bool:
        return row.event == event and all(
            str(row.payload.get(key, "other")) == value for key, value in fields.items()
        )

    return test


def _vital_measure(metric: str, screen: str) -> Callable[[Sequence[Row]], float | None]:
    test = _match("sx.web_vital", metric=metric, screen=screen)

    def measure(rows: Sequence[Row]) -> float | None:
        p75 = _percentile(_ms((row for row in rows if test(row)), "value"), 0.75)
        return float(p75) if p75 is not None else None

    return measure


def _denied_measure(permission: str) -> Callable[[Sequence[Row]], float | None]:
    def measure(rows: Sequence[Row]) -> float | None:
        states = [
            row.payload.get(permission) for row in rows if row.event == "sx.permission_snapshot"
        ]
        return _share(states.count("denied"), states.count("denied") + states.count("granted"))

    return measure


def _count_measure(test: Callable[[Row], bool]) -> Callable[[Sequence[Row]], float | None]:
    def measure(rows: Sequence[Row]) -> float | None:
        sessions = _sessions(rows)
        return round(sum(1 for row in rows if test(row)) * 100 / sessions, 2) if sessions else None

    return measure


def _findings(rows: Sequence[Row]) -> list[Finding]:
    found: list[Finding] = []
    # Slow actions, per screen.
    for (action, screen), items in _groups(
        [row for row in rows if row.event == "sx.action_timing"],
        lambda row: (
            str(row.payload.get("action", "other")),
            str(row.payload.get("screen", "other")),
        ),
    ).items():
        timing = _timing(items, action)
        if action == "other" or timing["taps"] < 10 or (timing["slow_share"] or 0) < 0.2:
            continue
        limit = _threshold(action)
        slow = [row for row in items if (_number(row.payload, "ms") or 0) > limit]
        tiers = Counter(str(row.payload.get("tier", "unknown")) for row in slow)
        found.append(
            Finding(
                key=f"slow:{action}:{screen}",
                kind="slow_action",
                title=f"{ACTION_LABELS.get(action, action)} is slow on {_screen_words(screen)}",
                screen=screen,
                severity=3 if action in KEY_ACTIONS else 2,
                people=len({row.person for row in slow}),
                events=len(slow),
                evidence={
                    **timing,
                    "slow_ms": limit,
                    "slow_tiers": [tier for tier, _ in tiers.most_common(2)],
                },
                measure=_slow_measure(action, screen),
                unit="ms",
            )
        )
    # Script errors, per place thrown (never the message); browser extensions are not ours.
    for (error, where), items in _groups(
        [
            row
            for row in rows
            if row.event == "sx.js_error" and row.payload.get("source") != "extension"
        ],
        lambda row: (str(row.payload.get("error", "error")), str(row.payload.get("where", ""))),
    ).items():
        screens = Counter(str(row.payload.get("screen", "other")) for row in items)
        screen = screens.most_common(1)[0][0]
        source = Counter(str(row.payload.get("source", "unknown")) for row in items).most_common(1)
        found.append(
            Finding(
                key=f"error:{error}:{where}",
                kind="script_error",
                title=f"Script error ({error}, {where}) on {_screen_words(screen)}",
                screen=screen,
                severity=3 if source and source[0][0] == "app" else 2,
                people=len({row.person for row in items}),
                events=len(items),
                evidence={
                    "count": len(items),
                    "source": source[0][0] if source else "unknown",
                    "screens": [name for name, _ in screens.most_common(3)],
                    "kind": Counter(str(r.payload.get("kind", "error")) for r in items).most_common(
                        1
                    )[0][0],
                },
                measure=_count_measure(_match("sx.js_error", error=error, where=where)),
                unit="per_100_sessions",
            )
        )
    # Server calls that fail or are slow.
    for endpoint, items in _groups(
        [row for row in rows if row.event == "sx.api_slow"],
        lambda row: str(row.payload.get("endpoint", "")),
    ).items():
        failed = [row for row in items if row.payload.get("status") == "5xx"]
        p75 = _percentile(_ms(items), 0.75)
        screen = Counter(str(row.payload.get("screen", "other")) for row in items).most_common(1)[
            0
        ][0]
        if len(failed) >= 3:
            found.append(
                Finding(
                    key=f"api_failed:{endpoint}",
                    kind="api_failed",
                    title=f"Server call {endpoint} fails",
                    screen=screen,
                    severity=3,
                    people=len({row.person for row in failed}),
                    events=len(failed),
                    evidence={"failed": len(failed), "calls": len(items), "p75": p75},
                    measure=_count_measure(_match("sx.api_slow", endpoint=endpoint, status="5xx")),
                    unit="per_100_sessions",
                )
            )
        elif len(items) >= 5 and (p75 or 0) >= 3_000:
            found.append(
                Finding(
                    key=f"api_slow:{endpoint}",
                    kind="api_slow",
                    title=f"Server call {endpoint} is slow",
                    screen=screen,
                    severity=2,
                    people=len({row.person for row in items}),
                    events=len(items),
                    evidence={"calls": len(items), "p75": p75},
                    measure=_count_measure(_match("sx.api_slow", endpoint=endpoint)),
                    unit="per_100_sessions",
                )
            )
    # Rage and dead taps.
    for (kind, screen, target), items in _groups(
        [row for row in rows if row.event == "sx.tap_issue"],
        lambda row: (
            str(row.payload.get("kind", "")),
            str(row.payload.get("screen", "other")),
            str(row.payload.get("target", "other")),
        ),
    ).items():
        if len(items) < 3 or kind not in ("rage", "dead"):
            continue
        found.append(
            Finding(
                key=f"tap:{kind}:{screen}:{target}",
                kind=f"{kind}_tap",
                title=(
                    f"Repeated taps on a {target} on {_screen_words(screen)}"
                    if kind == "rage"
                    else f"Taps on a {target} that does nothing on {_screen_words(screen)}"
                ),
                screen=screen,
                severity=2 if kind == "rage" else 1,
                people=len({row.person for row in items}),
                events=len(items),
                evidence={"count": len(items), "target": target},
                measure=_count_measure(
                    _match("sx.tap_issue", kind=kind, screen=screen, target=target)
                ),
                unit="per_100_sessions",
            )
        )
    # The Android app closing on people.
    for reason, items in _groups(
        [row for row in rows if row.event == "sx.app_exit"],
        lambda row: str(row.payload.get("reason", "other")),
    ).items():
        if reason not in CRASHES and reason not in KILLS:
            continue
        found.append(
            Finding(
                key=f"exit:{reason}",
                kind="app_exit",
                title={
                    "crash": "The Android app crashes",
                    "crash_native": "The Android app crashes (native code)",
                    "anr": "The Android app freezes (not responding)",
                    "low_memory": "Android closes the app for memory",
                    "excessive_resource": "Android closes the app for using too much",
                }[reason],
                screen="android_app",
                severity=4 if reason in CRASHES else 2,
                people=len({row.person for row in items}),
                events=len(items),
                evidence={
                    "count": len(items),
                    "foreground": sum(1 for row in items if row.payload.get("foreground") == "yes"),
                },
                measure=_count_measure(_match("sx.app_exit", reason=reason)),
                unit="per_100_sessions",
            )
        )
    # Slow pages (Largest paint, tap to paint) per screen.
    for (metric, screen), items in _groups(
        [
            row
            for row in rows
            if row.event == "sx.web_vital" and row.payload.get("metric") in ("lcp", "inp")
        ],
        lambda row: (str(row.payload.get("metric")), str(row.payload.get("screen", "other"))),
    ).items():
        values = _ms(items, "value")
        p75 = _percentile(values, 0.75)
        if len(values) < 10 or p75 is None or p75 <= VITAL_LIMITS[metric][1]:
            continue
        found.append(
            Finding(
                key=f"vital:{metric}:{screen}",
                kind="slow_page",
                title=(
                    f"{_screen_words(screen).capitalize()} paints slowly"
                    if metric == "lcp"
                    else f"Taps answer slowly on {_screen_words(screen)}"
                ),
                screen=screen,
                severity=2,
                people=len(
                    {
                        row.person
                        for row in items
                        if (_number(row.payload, "value") or 0) > VITAL_LIMITS[metric][1]
                    }
                ),
                events=len(values),
                evidence={"metric": metric, "p75": p75, "poor_over": VITAL_LIMITS[metric][1]},
                measure=_vital_measure(metric, screen),
                unit="ms",
            )
        )
    # Permissions the Android app needs that people refuse (their newest snapshot).
    newest: dict[str, Row] = {}
    for row in rows:
        if row.event == "sx.permission_snapshot" and (
            row.person not in newest or row.at > newest[row.person].at
        ):
            newest[row.person] = row
    for permission, label in (("calls", "calls"), ("rec_files", "recordings")):
        states = [str(row.payload.get(permission)) for row in newest.values()]
        denied = states.count("denied")
        asked = denied + states.count("granted")
        if asked >= 4 and denied / asked >= 0.25:
            found.append(
                Finding(
                    key=f"permission:{permission}",
                    kind="permission",
                    title=f"People refuse the Android app's {label} permission",
                    screen="android_app",
                    severity=2,
                    people=denied,
                    events=denied,
                    evidence={"denied": denied, "asked": asked, "share": _share(denied, asked)},
                    measure=_denied_measure(permission),
                    unit="share",
                )
            )
    return found


def _task(finding: Finding, owner: str, environment: str, window: str) -> str:
    evidence = ", ".join(f"{key} {value}" for key, value in finding.evidence.items())
    return (
        f"{finding.title}\n"
        f"{finding.people} people affected in {window} on {environment} "
        f"({SEVERITY_WORDS[finding.severity].lower()}; {finding.events} events).\n"
        f"Evidence: {evidence}.\n"
        f"Screen: {_screen_words(finding.screen)}. Suggested owner: {owner}.\n"
        f"Finding {finding.key}: Admin → Product telemetry → Fix next. After the fix ships, "
        "the same finding shows its measure by release."
    )


def fix_next(
    current: Sequence[Row],
    before: Sequence[Row],
    *,
    now: datetime,
    window: str,
    environment: str,
    limit: int = 25,
) -> dict[str, Any]:
    """What to fix next in the window, ranked by people affected times severity, with what
    improved since the window before (the measure of last week's fixes)."""
    findings = sorted(_findings(current), key=lambda item: (-item.score, -item.events, item.key))
    earlier = {item.key: item for item in _findings(before)}
    order = [item["release"] for item in release_order(current)]
    by_release = _groups(current, lambda row: row.release)
    items = []
    for finding in findings[:limit]:
        owner = OWNERS.get(finding.screen, DEFAULT_OWNER)
        was = earlier.get(finding.key)
        items.append(
            {
                "key": finding.key,
                "kind": finding.kind,
                "title": finding.title,
                "screen": finding.screen,
                "screen_label": _screen_words(finding.screen),
                "severity": finding.severity,
                "severity_label": SEVERITY_WORDS[finding.severity],
                "people": finding.people,
                "events": finding.events,
                "score": finding.score,
                "evidence": dict(finding.evidence),
                "unit": finding.unit,
                "now": finding.measure(current),
                "before": finding.measure(before) if before else None,
                "new": was is None,
                "by_release": [
                    {"release": release, "value": finding.measure(by_release[release])}
                    for release in order[-4:]
                ],
                "owner": owner,
                "task": _task(finding, owner, environment, window),
            }
        )
    current_keys = {item.key for item in findings}
    improved: list[dict[str, Any]] = []
    for key, finding in earlier.items():
        old, new = finding.measure(before), finding.measure(current)
        if key not in current_keys or (old is not None and new is not None and new < old * 0.8):
            improved.append(
                {
                    "key": key,
                    "title": finding.title,
                    "unit": finding.unit,
                    "before": old,
                    "now": new,
                    "gone": key not in current_keys,
                    "people_before": finding.people,
                }
            )
    improved.sort(key=lambda item: -item["people_before"])
    return {
        "schema": FIX_NEXT_SCHEMA,
        "environment": environment,
        "generated_at": now.isoformat(),
        "window": window,
        "since": (now - WINDOWS[window]).isoformat(),
        "items": items,
        "more": max(0, len(findings) - limit),
        "improved": improved[:15],
        "people": len({row.person for row in current}),
        "severity_words": dict(SEVERITY_WORDS),
    }


__all__ = [
    "COMPARE_SCHEMA",
    "DEVICES_SCHEMA",
    "FIX_NEXT_SCHEMA",
    "GATE_SCHEMA",
    "KEY_ACTIONS",
    "OWNERS",
    "THRESHOLDS",
    "compare",
    "devices",
    "fix_next",
    "gate",
    "release_order",
]

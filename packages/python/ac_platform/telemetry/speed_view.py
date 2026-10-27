"""Admin → Product telemetry → Speed and journeys (owner, 27 Oct 2026: "on low-end devices with
the worst processors this app might be slow... show things in the most beautiful, presentable
way").

How fast Sales X-Ray is on people's own phones, in the order the speed study found matters:

- Frames on Android: the share of frames slower than a refresh, and frozen ones, per app version
  and phone model (the strongest "it feels slow on my phone" signal).
- Slow API calls: per 100 screen views by release (a stalled server shows here first), and per
  endpoint, timed to the answer's first byte where the app says so (wait_ms, since 27 Oct).
- Load: largest paint and the app's start by device tier, the CPU test (cpu_ms) by tier and
  by phone model.
- Taps: each key action's time to respond by device tier.
- The journey from Leads (and from sign-in, once sign-ins are recorded): people at each step.

With few people every number carries its sample count, and the 95th percentile is left out
under MIN_P95 samples. Counts and timings only, read like the overview (admin_view.read_rows);
people are counted, never named or listed.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from ac_platform.telemetry.admin_view import (
    ACTION_LABELS,
    SLOW_MS,
    TIERS,
    VITAL_LIMITS,
    WINDOWS,
    Read,
    Row,
)

SCHEMA = "ac.sales-xray.speed-journeys/1"
# Below this many samples a 95th percentile is one or two values: left out.
MIN_P95 = 20
# Below this many, a number is shown as "few" (still with its count).
FEW = 5
KEY_ACTIONS = ("lead_open", "call_start", "tab_switch", "sheet_open", "report_open", "nav_switch")
# The CPU test's bands (telemetry.ts cpuTier, provisional).
CPU_BANDS: tuple[tuple[str, float], ...] = (("high", 3.0), ("mid", 6.0), ("low", float("inf")))


def _number(payload: Mapping[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _percentile(values: Sequence[float], share: float, digits: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    value = ordered[max(0, math.ceil(share * len(ordered)) - 1)]
    return round(value, digits) if digits else round(value)


def stat(values: Sequence[float], digits: int = 0) -> dict[str, Any]:
    """n, median, 75% and (from MIN_P95 samples) 95%, and whether it is too few to tell."""
    return {
        "n": len(values),
        "p50": _percentile(values, 0.5, digits),
        "p75": _percentile(values, 0.75, digits),
        "p95": _percentile(values, 0.95, digits) if len(values) >= MIN_P95 else None,
        "few": len(values) < FEW,
    }


def _share(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def _groups(rows: Iterable[Row], key: Callable[[Row], Any]) -> dict[Any, list[Row]]:
    grouped: dict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _values(rows: Iterable[Row], key: str) -> list[float]:
    return [value for row in rows if (value := _number(row.payload, key)) is not None]


def _models(by_event: Mapping[str, Sequence[Row]]) -> dict[str, str]:
    """Each person's phone model: their newest app start that names one, else their profile."""
    models: dict[str, tuple[datetime, str]] = {}
    for event in ("sx.device_profile", "sx.app_start"):
        for row in by_event.get(event, []):
            label = row.payload.get("model_label")
            if not isinstance(label, str) or not label:
                continue
            if row.person not in models or row.at > models[row.person][0]:
                models[row.person] = (row.at, label)
    return {person: label for person, (_, label) in models.items()}


def _frames(rows: Sequence[Row], models: Mapping[str, str]) -> dict[str, Any]:
    def summary(items: Sequence[Row]) -> dict[str, Any]:
        drawn = sum(_number(row.payload, "frames") or 0 for row in items)
        slow = sum(_number(row.payload, "slow") or 0 for row in items)
        frozen = sum(_number(row.payload, "frozen") or 0 for row in items)
        return {
            "sessions": len(items),
            "people": len({row.person for row in items}),
            "frames": int(drawn),
            "slow_share": _share(slow, drawn),
            "frozen_share": _share(frozen, drawn),
            # Each session reports its own 90th-percentile frame; these are across sessions.
            "p90_ms": stat(_values(items, "p90_ms")),
        }

    versions = sorted(
        _groups(rows, lambda row: str(row.payload.get("app_version") or "unknown")).items(),
        key=lambda pair: (-max(row.at for row in pair[1]).timestamp(), pair[0]),
    )
    phones = sorted(
        _groups(rows, lambda row: models.get(row.person, "unknown")).items(),
        key=lambda pair: -len(pair[1]),
    )
    return {
        "all": summary(rows),
        "by_version": [{"version": version, **summary(items)} for version, items in versions[:6]],
        "by_model": [{"model": model, **summary(items)} for model, items in phones[:8]],
    }


def _apis(rows: Sequence[Row], views: Sequence[Row]) -> dict[str, Any]:
    slow = [row for row in rows if row.event == "sx.api_slow"]
    releases = _groups(slow + list(views), lambda row: row.release or "unknown")
    by_release = []
    for release, items in sorted(
        releases.items(), key=lambda pair: -min(row.at for row in pair[1]).timestamp()
    )[:6]:
        calls = [row for row in items if row.event == "sx.api_slow"]
        seen = sum(1 for row in items if row.event == "sx.screen_viewed")
        by_release.append(
            {
                "release": release,
                "first_at": min(row.at for row in items).isoformat(),
                "slow_calls": len(calls),
                "screen_views": seen,
                "per_100_views": round(100 * len(calls) / seen, 1) if seen else None,
                "people": len({row.person for row in calls}),
            }
        )
    endpoints = []
    for endpoint, items in sorted(
        _groups(slow, lambda row: str(row.payload.get("endpoint", ""))).items(),
        key=lambda pair: -len(pair[1]),
    )[:12]:
        statuses = Counter(str(row.payload.get("status", "unknown")) for row in items)
        endpoints.append(
            {
                "endpoint": endpoint,
                "calls": len(items),
                "people": len({row.person for row in items}),
                # To the first byte where the app says so (27 Oct 2026); the whole call before.
                "wait": stat(_values(items, "wait_ms")),
                "total": stat(_values(items, "ms")),
                "failed": statuses.get("5xx", 0),
                "refused": statuses.get("4xx", 0),
                "screens": [
                    screen
                    for screen, _ in Counter(
                        str(row.payload.get("screen", "other")) for row in items
                    ).most_common(3)
                ],
            }
        )
    return {
        "calls": len(slow),
        "people": len({row.person for row in slow}),
        "screen_views": len(views),
        "per_100_views": round(100 * len(slow) / len(views), 1) if views else None,
        "by_release": by_release,
        "endpoints": endpoints,
    }


def _rating(metric: str, value: int | None) -> str | None:
    if value is None or metric not in VITAL_LIMITS:
        return None
    good, poor = VITAL_LIMITS[metric]
    return "good" if value <= good else "poor" if value > poor else "needs_improvement"


def _cpu_band(milliseconds: float) -> str:
    return next(band for band, limit in CPU_BANDS if milliseconds < limit)


def _load(by_event: Mapping[str, Sequence[Row]], models: Mapping[str, str]) -> dict[str, Any]:
    paints = [row for row in by_event.get("sx.web_vital", []) if row.payload.get("metric") == "lcp"]
    starts = by_event.get("sx.app_start", [])
    launches = by_event.get("sx.app_launch", [])
    lcp_by_tier = []
    for tier in TIERS:
        values = _values(
            [row for row in paints if row.payload.get("tier", "unknown") == tier], "value"
        )
        if values:
            summary = stat(values)
            lcp_by_tier.append({"tier": tier, **summary, "rating": _rating("lcp", summary["p75"])})
    start_rows = []
    for (app, start), items in sorted(
        _groups(
            starts,
            lambda row: (str(row.payload.get("app", "web")), str(row.payload.get("start", "cold"))),
        ).items()
    ):
        start_rows.append(
            {"app": app, "start": start, "what": "page", **stat(_values(items, "ms"))}
        )
    for start, items in sorted(
        _groups(launches, lambda row: str(row.payload.get("start", "cold"))).items()
    ):
        start_rows.append(
            {"app": "android", "start": start, "what": "launch", **stat(_values(items, "ms"))}
        )
    tested = [row for row in starts if _number(row.payload, "cpu_ms") is not None]
    cpu_bands = Counter(_cpu_band(_number(row.payload, "cpu_ms") or 0.0) for row in tested)
    by_model = []
    for model, items in sorted(
        _groups(tested, lambda row: models.get(row.person, "unknown")).items(),
        key=lambda pair: -len(pair[1]),
    )[:10]:
        cpu = stat(_values(items, "cpu_ms"), digits=1)
        by_model.append(
            {
                "model": model,
                "people": len({row.person for row in items}),
                "cpu": cpu,
                "tier": _cpu_band(cpu["p50"]),
                "start": stat(_values(items, "ms")),
            }
        )
    return {
        "lcp_by_tier": lcp_by_tier,
        "starts": start_rows,
        "cpu": {
            "tests": len(tested),
            "people": len({row.person for row in tested}),
            "all": stat(_values(tested, "cpu_ms"), digits=1),
            "bands": {band: cpu_bands.get(band, 0) for band, _ in CPU_BANDS},
            "by_model": by_model,
        },
    }


def _taps(rows: Sequence[Row]) -> list[dict[str, Any]]:
    out = []
    by_action = _groups(rows, lambda row: str(row.payload.get("action", "other")))
    for action in KEY_ACTIONS:
        items = by_action.get(action, [])
        if not items:
            continue
        limit = SLOW_MS.get(action, 1_000)
        out.append(
            {
                "action": action,
                "label": ACTION_LABELS.get(action, action),
                "slow_ms": limit,
                "all": stat(_values(items, "ms")),
                "by_tier": [
                    {
                        "tier": tier,
                        **stat(values),
                        "slow_share": _share(
                            sum(1 for value in values if value > limit), len(values)
                        ),
                    }
                    for tier in TIERS
                    if (
                        values := _values(
                            [row for row in items if row.payload.get("tier", "unknown") == tier],
                            "ms",
                        )
                    )
                ],
            }
        )
    return out


JOURNEY: tuple[tuple[str, str, Callable[[Row], bool]], ...] = (
    ("signed_in", "Signed in", lambda r: r.event == "sx.sign_in"),
    (
        "leads",
        "Opened Leads",
        lambda r: r.event == "sx.screen_viewed" and r.payload.get("screen") in ("leads", "lead"),
    ),
    (
        "lead",
        "Opened a lead",
        lambda r: r.event == "sx.action_timing" and r.payload.get("action") == "lead_open",
    ),
    (
        "call",
        "Started a call",
        lambda r: r.event == "sx.action_timing" and r.payload.get("action") == "call_start",
    ),
    ("upload", "Started an upload", lambda r: r.event == "sx.upload_started"),
    (
        "saved",
        "Upload finished",
        lambda r: r.event == "sx.upload_finished" and r.payload.get("outcome") == "saved",
    ),
    ("report", "Opened a report", lambda r: r.event == "sx.report_opened"),
)


def journey(rows: Sequence[Row]) -> dict[str, Any]:
    """People at each step from Leads to a report; from sign-in once any sign-in is recorded.

    A person counts at a step when they also reached every step before it in the window (not
    necessarily in order within one session).
    """
    reached = {key: {row.person for row in rows if test(row)} for key, _, test in JOURNEY}
    steps = [step for step in JOURNEY if step[0] != "signed_in" or reached["signed_in"]]
    out: list[dict[str, Any]] = []
    so_far: set[str] | None = None
    first = 0
    for key, label, _ in steps:
        so_far = set(reached[key]) if so_far is None else so_far & reached[key]
        if not out:
            first = len(so_far)
        before = out[-1]["people"] if out else None
        out.append(
            {
                "key": key,
                "label": label,
                "people": len(so_far),
                "of_first": _share(len(so_far), first),
                "of_previous": _share(len(so_far), before) if before is not None else None,
            }
        )
    return {"from": steps[0][0] if steps else "leads", "steps": out}


def speed(
    read: Read, *, now: datetime, window: str, app: str | None, environment: str
) -> dict[str, Any]:
    """The Speed and journeys page for one window (pure: the caller reads the rows)."""
    rows = [row for row in read.rows if app is None or row.payload.get("app") == app]
    by_event = _groups(rows, lambda row: row.event)
    models = _models(by_event)
    return {
        "schema": SCHEMA,
        "environment": environment,
        "generated_at": now.isoformat(),
        "window": window,
        "since": (now - WINDOWS[window]).isoformat(),
        "app": app,
        "min_p95": MIN_P95,
        "few": FEW,
        "truncated": read.truncated,
        "totals": {
            "people": len({row.person for row in rows}),
            "sessions": len({row.session for row in rows if row.session}),
            "events": len(rows),
        },
        "frames": _frames(by_event.get("sx.app_frames", []), models),
        "apis": _apis(rows, by_event.get("sx.screen_viewed", [])),
        "load": _load(by_event, models),
        "taps": _taps(by_event.get("sx.action_timing", [])),
        "journey": journey(rows),
    }


__all__ = ["FEW", "KEY_ACTIONS", "MIN_P95", "SCHEMA", "journey", "speed", "stat"]

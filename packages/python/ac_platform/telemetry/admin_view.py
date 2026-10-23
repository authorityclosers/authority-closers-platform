"""Admin's view of Sales X-Ray product telemetry (owner, 24 Oct 2026: "Build full performance
and usage telemetry with the Admin dashboard"; "40% of devices are slow when clicking a
lead").

Counts and timings only, read from this environment's ``analytics_events`` (the Sales X-Ray
retention policy, never an expired row):

- Speed: each key action's tap-to-response time, its slow share (taps over the action's
  threshold) and slow-device share (devices, a person on one device class and tier, whose
  median is over it), by device tier, device class and release.
- Web Vitals and the app's start, per screen and device class.
- Screens: views, people, time stayed, exits, the busiest transitions, and a heatmap by
  day (by hour over 24 hours).
- Funnels (reports and leads), feature adoption, errors, slow APIs, rage and dead taps.
- Who is recorded: the workspaces and people who turned it off.

People and workspaces are only ever counted here, never named or listed.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.sales_xray import RETENTION_POLICY_ID
from ac_platform.telemetry.sales_xray_consent import RESOURCE_TYPE, WORKSPACE_RESOURCE

SCHEMA = "ac.sales-xray.product-telemetry/1"
INDIA = ZoneInfo("Asia/Kolkata")
WINDOWS: Mapping[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
MAX_ROWS = 200_000
DEVICES = ("phone", "tablet", "desktop")
TIERS = ("low", "mid", "high", "unknown")
APPS = ("web", "android")
# What "slow" means for each action, in milliseconds from the tap to the screen settling.
SLOW_MS: Mapping[str, int] = {
    "lead_open": 1_000,
    "call_start": 1_000,
    "tab_switch": 500,
    "outcome_save": 1_000,
    "report_open": 1_500,
    "nav_switch": 1_000,
    "sheet_open": 500,
}
DEFAULT_SLOW_MS = 1_000
# web.dev's thresholds (CLS times 1,000), for the 75th percentile's rating.
VITAL_LIMITS: Mapping[str, tuple[int, int]] = {
    "lcp": (2_500, 4_000),
    "inp": (200, 500),
    "cls": (100, 250),
    "fcp": (1_800, 3_000),
    "ttfb": (800, 1_800),
}
ACTION_LABELS: Mapping[str, str] = {
    "lead_open": "Open a lead",
    "call_start": "Call",
    "tab_switch": "Switch tab",
    "outcome_save": "Save outcome",
    "report_open": "Open a report",
    "nav_switch": "Go to a screen",
    "sheet_open": "Open a sheet",
    "search": "Search",
    "save": "Save",
    "send": "Send",
    "filter": "Filter",
    "back": "Back",
    "other": "Other",
}


@dataclass(frozen=True)
class Row:
    event: str
    at: datetime
    release: str
    person: str
    workspace: str
    session: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Filters:
    release: str | None = None
    device: str | None = None
    app: str | None = None
    tier: str | None = None

    def keep(self, row: Row) -> bool:
        payload = row.payload
        return (
            (self.release is None or row.release == self.release)
            and (self.device is None or payload.get("device") == self.device)
            and (self.app is None or payload.get("app") == self.app)
            and (self.tier is None or payload.get("tier") == self.tier)
        )


@dataclass
class Read:
    rows: list[Row] = field(default_factory=list)
    truncated: bool = False


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def read_rows(
    connection: Any, *, since: datetime, until: datetime, now: datetime, limit: int = MAX_ROWS
) -> Read:
    """This environment's Sales X-Ray events in [since, until), newest first, never expired."""
    result = connection.execute(
        select(
            AnalyticsEvent.event_name,
            AnalyticsEvent.occurred_at,
            AnalyticsEvent.release_id,
            AnalyticsEvent.subject_person_id,
            AnalyticsEvent.tenant_id,
            AnalyticsEvent.session_id,
            AnalyticsEvent.payload,
        )
        .where(
            AnalyticsEvent.retention_policy_id == RETENTION_POLICY_ID,
            AnalyticsEvent.occurred_at >= since,
            AnalyticsEvent.occurred_at < until,
            AnalyticsEvent.retention_expires_at > now,
        )
        .order_by(AnalyticsEvent.occurred_at.desc())
        .limit(limit + 1)
    ).all()
    rows = [
        Row(
            event=str(name),
            at=_utc(at),
            release=str(release or ""),
            person=str(person),
            workspace=str(workspace),
            session=str(session) if session else None,
            payload=payload if isinstance(payload, dict) else {},
        )
        for name, at, release, person, workspace, session, payload in result[:limit]
    ]
    return Read(rows=rows, truncated=len(result) > limit)


def read_consent(connection: Any) -> dict[str, int]:
    """How many people and workspaces turned usage analytics off (their newest choice)."""
    newest: dict[tuple[str, str], tuple[datetime, int, bool]] = {}
    for tenant, resource, payload, at, sequence in connection.execute(
        select(
            AuditEvent.tenant_id,
            AuditEvent.resource_id,
            AuditEvent.payload,
            AuditEvent.occurred_at,
            AuditEvent.sequence_no,
        ).where(AuditEvent.resource_type == RESOURCE_TYPE)
    ):
        enabled = not (isinstance(payload, dict) and payload.get("enabled") is False)
        # A person's choice holds everywhere: keyed by the person alone.
        key = (str(tenant), "workspace") if resource == WORKSPACE_RESOURCE else ("", str(resource))
        moment = (_utc(at), int(sequence), enabled)
        if key not in newest or moment[:2] > newest[key][:2]:
            newest[key] = moment
    return {
        "workspaces_off": sum(
            1 for (tenant, kind), item in newest.items() if kind == "workspace" and not item[2]
        ),
        "people_off": sum(
            1 for (tenant, kind), item in newest.items() if tenant == "" and not item[2]
        ),
    }


def _percentile(values: Sequence[float], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(share * len(ordered)) - 1)
    return round(ordered[index])


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _number(payload: Mapping[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _groups(rows: Iterable[Row], key: Callable[[Row], Any]) -> dict[Any, list[Row]]:
    grouped: dict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _timing_summary(rows: Sequence[Row], threshold: int) -> dict[str, Any]:
    values = [value for row in rows if (value := _number(row.payload, "ms")) is not None]
    return {
        "taps": len(values),
        "p50": _percentile(values, 0.5),
        "p75": _percentile(values, 0.75),
        "p95": _percentile(values, 0.95),
        "slow_share": _share(sum(1 for value in values if value > threshold), len(values)),
    }


def _speed(rows: Sequence[Row]) -> list[dict[str, Any]]:
    out = []
    for action, items in sorted(
        _groups(rows, lambda row: str(row.payload.get("action", "other"))).items(),
        key=lambda pair: -len(pair[1]),
    ):
        threshold = SLOW_MS.get(action, DEFAULT_SLOW_MS)
        # A device is a person on one device class and tier.
        devices = _groups(
            items,
            lambda row: (
                row.person,
                row.payload.get("device", "unknown"),
                row.payload.get("tier", "unknown"),
            ),
        )
        medians = [
            median(values)
            for group in devices.values()
            if (values := [v for row in group if (v := _number(row.payload, "ms")) is not None])
        ]
        paints = [v for row in items if (v := _number(row.payload, "paint_ms")) is not None]
        results = Counter(str(row.payload.get("result", "settled")) for row in items)
        by_release = _groups(items, lambda row: row.release)
        out.append(
            {
                "action": action,
                "label": ACTION_LABELS.get(action, action),
                "slow_ms": threshold,
                **_timing_summary(items, threshold),
                "people": len({row.person for row in items}),
                "devices": len(medians),
                "slow_device_share": _share(
                    sum(1 for value in medians if value > threshold), len(medians)
                ),
                "paint_p75": _percentile(paints, 0.75),
                "results": {
                    key: results.get(key, 0) for key in ("settled", "timeout", "no_change")
                },
                "by_tier": [
                    {"tier": tier, **_timing_summary(group, threshold)}
                    for tier in TIERS
                    if (
                        group := [
                            row for row in items if row.payload.get("tier", "unknown") == tier
                        ]
                    )
                ],
                "by_device": [
                    {"device": device, **_timing_summary(group, threshold)}
                    for device in DEVICES
                    if (group := [row for row in items if row.payload.get("device") == device])
                ],
                "by_release": [
                    {"release": release, **_timing_summary(group, threshold)}
                    for release, group in sorted(
                        by_release.items(), key=lambda pair: -len(pair[1])
                    )[:6]
                ],
            }
        )
    return out


def _rating(metric: str, value: int | None) -> str | None:
    if value is None or metric not in VITAL_LIMITS:
        return None
    good, poor = VITAL_LIMITS[metric]
    return "good" if value <= good else "poor" if value > poor else "needs_improvement"


def _vitals(rows: Sequence[Row]) -> list[dict[str, Any]]:
    out = []
    for metric in ("lcp", "inp", "cls", "fcp", "ttfb"):
        items = [row for row in rows if row.payload.get("metric") == metric]
        values = [v for row in items if (v := _number(row.payload, "value")) is not None]
        if not values:
            continue
        ratings = Counter(str(row.payload.get("rating", "")) for row in items)
        p75 = _percentile(values, 0.75)
        screens = _groups(items, lambda row: str(row.payload.get("screen", "other")))
        out.append(
            {
                "metric": metric,
                "samples": len(values),
                "p75": p75,
                "rating": _rating(metric, p75),
                "shares": {
                    key: _share(ratings.get(key, 0), len(items))
                    for key in ("good", "needs_improvement", "poor")
                },
                "by_device": [
                    {
                        "device": device,
                        "samples": len(group),
                        "p75": _percentile(
                            [v for r in group if (v := _number(r.payload, "value")) is not None],
                            0.75,
                        ),
                    }
                    for device in DEVICES
                    if (group := [row for row in items if row.payload.get("device") == device])
                ],
                "by_screen": [
                    {
                        "screen": screen,
                        "samples": len(group),
                        "p75": _percentile(
                            [v for r in group if (v := _number(r.payload, "value")) is not None],
                            0.75,
                        ),
                    }
                    for screen, group in sorted(screens.items(), key=lambda pair: -len(pair[1]))[:8]
                ],
            }
        )
    return out


def _starts(rows: Sequence[Row]) -> list[dict[str, Any]]:
    out = []
    for (start, app), items in sorted(
        _groups(
            rows,
            lambda row: (str(row.payload.get("start", "cold")), str(row.payload.get("app", "web"))),
        ).items()
    ):
        values = [v for row in items if (v := _number(row.payload, "ms")) is not None]
        out.append(
            {
                "start": start,
                "app": app,
                "samples": len(values),
                "p50": _percentile(values, 0.5),
                "p75": _percentile(values, 0.75),
            }
        )
    return out


def _bucket(moment: datetime, hourly: bool) -> str:
    local = moment.astimezone(INDIA)
    return local.strftime("%Y-%m-%dT%H:00") if hourly else local.date().isoformat()


def _buckets(since: datetime, now: datetime, hourly: bool) -> list[str]:
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    keys: list[str] = []
    moment = since
    while moment <= now:
        key = _bucket(moment, hourly)
        if key not in keys:
            keys.append(key)
        moment += step
    last = _bucket(now, hourly)
    if last not in keys:
        keys.append(last)
    return keys


def _screens(views: Sequence[Row], since: datetime, now: datetime, hourly: bool) -> dict[str, Any]:
    buckets = _buckets(since, now, hourly)
    by_screen = _groups(views, lambda row: str(row.payload.get("screen", "other")))
    # Time on a screen arrives with the next view (its stay_ms for "from").
    stays: dict[str, list[float]] = defaultdict(list)
    for row in views:
        stay = _number(row.payload, "stay_ms")
        origin = row.payload.get("from")
        if stay is not None and isinstance(origin, str) and origin != "none":
            stays[origin].append(stay)
    # The last screen of each session is where it ended.
    last: dict[str, Row] = {}
    for row in views:
        if row.session and (row.session not in last or row.at > last[row.session].at):
            last[row.session] = row
    exits = Counter(str(row.payload.get("screen", "other")) for row in last.values())
    sessions_on = {
        screen: len({row.session for row in items if row.session})
        for screen, items in by_screen.items()
    }
    rows_out = []
    for screen, items in sorted(by_screen.items(), key=lambda pair: -len(pair[1])):
        counts = Counter(_bucket(row.at, hourly) for row in items)
        rows_out.append(
            {
                "screen": screen,
                "views": len(items),
                "people": len({row.person for row in items}),
                "stay_p50": _percentile(stays.get(screen, []), 0.5),
                "exit_share": _share(exits.get(screen, 0), sessions_on.get(screen, 0)),
                "heat": [counts.get(bucket, 0) for bucket in buckets],
            }
        )
    flows = Counter(
        (str(row.payload.get("from")), str(row.payload.get("screen")))
        for row in views
        if row.payload.get("from") not in (None, "none")
    )
    return {
        "buckets": buckets,
        "hourly": hourly,
        "rows": rows_out,
        "flows": [
            {"from": origin, "to": target, "count": count}
            for (origin, target), count in flows.most_common(15)
        ],
    }


def _funnel(steps: Sequence[tuple[str, str, set[str]]]) -> list[dict[str, Any]]:
    out = []
    first = len(steps[0][2]) if steps else 0
    reached: set[str] | None = None
    for key, label, people in steps:
        reached = set(people) if reached is None else reached & people
        out.append(
            {
                "key": key,
                "label": label,
                "people": len(reached),
                "share": _share(len(reached), first),
            }
        )
    return out


def _people(rows: Iterable[Row], test: Callable[[Row], bool]) -> set[str]:
    return {row.person for row in rows if test(row)}


def _funnels(rows: Sequence[Row]) -> list[dict[str, Any]]:
    report = _funnel(
        [
            ("opened", "Opened a report", _people(rows, lambda r: r.event == "sx.report_opened")),
            (
                "read",
                "Read a section 5 s or more",
                _people(
                    rows,
                    lambda r: (
                        r.event == "sx.section_read"
                        and r.payload.get("read_band") not in (None, "under_5s")
                    ),
                ),
            ),
            (
                "full",
                "Asked for the full report",
                _people(rows, lambda r: r.event == "sx.full_report_requested"),
            ),
            ("outcome", "Saved an outcome", _people(rows, lambda r: r.event == "sx.outcome_set")),
        ]
    )
    leads = _funnel(
        [
            (
                "leads",
                "Opened Leads",
                _people(
                    rows,
                    lambda r: (
                        r.event == "sx.screen_viewed"
                        and r.payload.get("screen") in ("leads", "lead")
                    ),
                ),
            ),
            (
                "lead",
                "Opened a lead",
                _people(
                    rows,
                    lambda r: (
                        r.event == "sx.action_timing" and r.payload.get("action") == "lead_open"
                    ),
                ),
            ),
            (
                "call",
                "Called",
                _people(
                    rows,
                    lambda r: (
                        r.event == "sx.action_timing" and r.payload.get("action") == "call_start"
                    ),
                ),
            ),
            ("outcome", "Saved an outcome", _people(rows, lambda r: r.event == "sx.outcome_set")),
        ]
    )
    return [
        {"key": "report", "label": "From a report to an outcome", "steps": report},
        {"key": "leads", "label": "From Leads to an outcome", "steps": leads},
    ]


# Features, by what shows they were used.
FEATURES: tuple[tuple[str, str, Callable[[Row], bool]], ...] = (
    ("report", "Reports", lambda r: r.event == "sx.report_opened"),
    (
        "coaching_score",
        "AI coaching score",
        lambda r: r.event == "sx.section_read" and r.payload.get("section") == "analysis",
    ),
    (
        "coaching",
        "Coaching",
        lambda r: (
            r.event == "sx.coaching_opened"
            or (r.event == "sx.screen_viewed" and r.payload.get("screen") == "coaching")
        ),
    ),
    ("full_report", "Get full report", lambda r: r.event == "sx.full_report_requested"),
    ("reanalyse", "Analyse again", lambda r: r.event == "sx.reanalyse_requested"),
    ("outcome", "Deal outcome", lambda r: r.event == "sx.outcome_set"),
    ("upload", "Upload a call", lambda r: r.event == "sx.upload_started"),
    ("clip", "Play a clip", lambda r: r.event == "sx.clip_played"),
    (
        "leads",
        "Leads",
        lambda r: r.event == "sx.screen_viewed" and r.payload.get("screen") in ("leads", "lead"),
    ),
    (
        "calling",
        "Calling from the app",
        lambda r: r.event == "sx.action_timing" and r.payload.get("action") == "call_start",
    ),
    (
        "chats",
        "Chats",
        lambda r: r.event == "sx.screen_viewed" and r.payload.get("screen") == "chats",
    ),
    (
        "prospects",
        "Prospects",
        lambda r: (
            r.event == "sx.screen_viewed" and r.payload.get("screen") in ("prospects", "prospect")
        ),
    ),
)


def _features(rows: Sequence[Row]) -> dict[str, Any]:
    active = {row.person for row in rows}
    counts = [(key, label, len(_people(rows, test))) for key, label, test in FEATURES]
    for feature, items in _groups(
        [row for row in rows if row.event == "sx.feature_used"],
        lambda row: str(row.payload.get("feature", "")),
    ).items():
        if feature:
            counts.append((feature, feature, len({r.person for r in items})))
    return {
        "active_people": len(active),
        "rows": [
            {"feature": key, "label": label, "people": people, "share": _share(people, len(active))}
            for key, label, people in sorted(counts, key=lambda item: -item[2])
        ],
    }


def _top(values: Iterable[str], count: int = 3) -> list[str]:
    return [value for value, _ in Counter(values).most_common(count)]


def _errors(rows: Sequence[Row]) -> dict[str, Any]:
    scripts = []
    for (error, where), items in sorted(
        _groups(
            [row for row in rows if row.event == "sx.js_error"],
            lambda row: (str(row.payload.get("error", "error")), str(row.payload.get("where", ""))),
        ).items(),
        key=lambda pair: -len(pair[1]),
    )[:25]:
        scripts.append(
            {
                "error": error,
                "where": where,
                "kind": _top(str(row.payload.get("kind", "error")) for row in items)[0],
                "source": _top(str(row.payload.get("source", "unknown")) for row in items)[0],
                "count": len(items),
                "people": len({row.person for row in items}),
                "screens": _top(str(row.payload.get("screen", "other")) for row in items),
                "releases": _top(row.release for row in items),
                "last_at": max(row.at for row in items).isoformat(),
            }
        )
    apis = []
    for endpoint, items in sorted(
        _groups(
            [row for row in rows if row.event == "sx.api_slow"],
            lambda row: str(row.payload.get("endpoint", "")),
        ).items(),
        key=lambda pair: -len(pair[1]),
    )[:25]:
        values = [v for row in items if (v := _number(row.payload, "ms")) is not None]
        apis.append(
            {
                "endpoint": endpoint,
                "count": len(items),
                "failed": sum(1 for row in items if row.payload.get("status") == "5xx"),
                "p75": _percentile(values, 0.75),
                "screens": _top(str(row.payload.get("screen", "other")) for row in items),
            }
        )
    taps = [
        {
            "kind": kind,
            "screen": screen,
            "target": target,
            "count": len(items),
            "people": len({row.person for row in items}),
        }
        for (kind, screen, target), items in sorted(
            _groups(
                [row for row in rows if row.event == "sx.tap_issue"],
                lambda row: (
                    str(row.payload.get("kind", "")),
                    str(row.payload.get("screen", "other")),
                    str(row.payload.get("target", "other")),
                ),
            ).items(),
            key=lambda pair: -len(pair[1]),
        )[:25]
    ]
    shown = [
        {"surface": surface, "code": code, "count": len(items)}
        for (surface, code), items in sorted(
            _groups(
                [row for row in rows if row.event == "sx.error_shown"],
                lambda row: (str(row.payload.get("surface", "")), str(row.payload.get("code", ""))),
            ).items(),
            key=lambda pair: -len(pair[1]),
        )[:25]
    ]
    return {"scripts": scripts, "apis": apis, "taps": taps, "shown": shown}


def _mix(rows: Sequence[Row]) -> dict[str, Any]:
    people_by: dict[str, dict[str, set[str]]] = {
        key: defaultdict(set) for key in ("device", "tier", "app", "net")
    }
    for row in rows:
        for key in people_by:
            people_by[key][str(row.payload.get(key, "unknown"))].add(row.person)
    return {
        key: [
            {"value": value, "people": len(people)}
            for value, people in sorted(groups.items(), key=lambda pair: -len(pair[1]))
        ]
        for key, groups in people_by.items()
    }


def _releases(rows: Sequence[Row]) -> list[dict[str, Any]]:
    out = []
    for release, items in sorted(
        _groups(rows, lambda row: row.release).items(), key=lambda pair: -len(pair[1])
    )[:10]:
        opens = [
            row
            for row in items
            if row.event == "sx.action_timing" and row.payload.get("action") == "lead_open"
        ]
        out.append(
            {
                "release": release,
                "events": len(items),
                "people": len({row.person for row in items}),
                "first_at": min(row.at for row in items).isoformat(),
                "lead_open": _timing_summary(opens, SLOW_MS["lead_open"]),
                "script_errors": sum(1 for row in items if row.event == "sx.js_error"),
            }
        )
    return out


def overview(
    read: Read,
    *,
    now: datetime,
    window: str,
    filters: Filters,
    consent: Mapping[str, int],
    environment: str,
) -> dict[str, Any]:
    """The dashboard for one window and filter (pure: the caller reads the rows)."""
    since = now - WINDOWS[window]
    releases = sorted({row.release for row in read.rows if row.release})
    rows = [row for row in read.rows if filters.keep(row)]
    by_event = _groups(rows, lambda row: row.event)
    return {
        "schema": SCHEMA,
        "environment": environment,
        "generated_at": now.isoformat(),
        "window": window,
        "since": since.isoformat(),
        "filters": {
            "release": filters.release,
            "device": filters.device,
            "app": filters.app,
            "tier": filters.tier,
            "releases": releases,
        },
        "rows_read": len(read.rows),
        "truncated": read.truncated,
        "totals": {
            "events": len(rows),
            "people": len({row.person for row in rows}),
            "sessions": len({row.session for row in rows if row.session}),
            "workspaces": len({row.workspace for row in rows}),
        },
        "consent": dict(consent),
        "speed": _speed(by_event.get("sx.action_timing", [])),
        "vitals": _vitals(by_event.get("sx.web_vital", [])),
        "starts": _starts(by_event.get("sx.app_start", [])),
        "screens": _screens(by_event.get("sx.screen_viewed", []), since, now, window == "24h"),
        "funnels": _funnels(rows),
        "features": _features(rows),
        "errors": _errors(rows),
        "mix": _mix(rows),
        "releases": _releases(rows),
    }


__all__ = [
    "DEFAULT_SLOW_MS",
    "SCHEMA",
    "SLOW_MS",
    "WINDOWS",
    "Filters",
    "Read",
    "Row",
    "overview",
    "read_consent",
    "read_rows",
]

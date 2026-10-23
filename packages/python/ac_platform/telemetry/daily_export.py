"""The daily telemetry export for the cost optimiser (cost-research's spec, 23 Oct 2026):
what each analysed call cost and how its report was used.

One India day (Asia/Kolkata), this environment only, pseudonymous and content-free:

- ``calls``: every call this environment first analysed that day (its C2 transcription),
  opened or not, by ``call_ref``: workspace and seller pseudonyms, length band, pipeline
  version, cost and C5 (report) cost in paise, how often and how soon its report was opened,
  which sections were read (the longest read band, summed dwell, each action) and what was
  asked for on demand. Calls analysed but never opened are what precomputing wasted.
- ``workspaces``: that day's section reads, actions and on-demand asks per workspace, and
  analysed, opened and opened-within-24-hours calls.

Telemetry for the day's calls is read up to 7 days on, so later opens still count. The AI
level at analysis is not in the cost store yet, so it is left out (null).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from ac_platform.conversation_intelligence.cost_metrics import (
    INDIA,
    TEST_KINDS,
    Export,
    india_day,
    version_id,
)
from ac_platform.telemetry.admin_view import Row
from ac_platform.telemetry.sales_xray import call_ref

SCHEMA = "ac.sales-xray.telemetry-daily/1"
FOLLOW = timedelta(days=7)
BANDS = ("under_5s", "5_30s", "30_120s", "over_120s")
LENGTH_BANDS: tuple[tuple[float, str], ...] = (
    (1, "under_1"),
    (3, "1_3"),
    (6, "3_6"),
    (10, "6_10"),
    (20, "10_20"),
)


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=INDIA)
    return start, start + timedelta(days=1)


def workspace_ref(inner: bytes, outer: bytes, tenant_id: str) -> str:
    """``w_`` and 16 hex characters of HMAC(key, ``workspace:`` and the tenant id)."""
    message = f"workspace:{tenant_id}".encode()
    digest = hashlib.sha256(outer + hashlib.sha256(inner + message).digest()).hexdigest()
    return "w_" + digest[:16]


def length_band(minutes: float) -> str:
    for limit, band in LENGTH_BANDS:
        if minutes < limit:
            return band
    return "over_20"


def _band_rank(band: Any) -> int:
    return BANDS.index(band) if band in BANDS else -1


def _call_usage(events: Sequence[Row], report_at: datetime | None) -> dict[str, Any]:
    opens = sorted(row.at for row in events if row.event == "sx.report_opened")
    looks = Counter(
        str(row.payload["look"])
        for row in events
        if row.event == "sx.section_read" and "look" in row.payload
    )
    sections: dict[str, dict[str, Any]] = {}
    for row in events:
        if row.event not in ("sx.section_read", "sx.section_action"):
            continue
        name = str(row.payload.get("section", "other"))
        entry = sections.setdefault(
            name, {"section": name, "max_band": None, "dwell_ms": 0, "actions": {}}
        )
        if row.event == "sx.section_read":
            band = row.payload.get("read_band")
            if _band_rank(band) > _band_rank(entry["max_band"]):
                entry["max_band"] = band
            dwell = row.payload.get("dwell_ms")
            if isinstance(dwell, int | float) and not isinstance(dwell, bool):
                entry["dwell_ms"] += round(dwell)
        else:
            action = str(row.payload.get("action", "other"))
            entry["actions"][action] = entry["actions"].get(action, 0) + 1
    first_open = (
        round((opens[0] - report_at).total_seconds())
        if opens and report_at is not None and opens[0] >= report_at
        else None
    )
    return {
        "opened": len(opens),
        "look": looks.most_common(1)[0][0] if looks else None,
        "sections": sorted(sections.values(), key=lambda item: item["section"]),
        "on_demand": [
            {"section": row.payload.get("section"), "level": row.payload.get("level")}
            for row in events
            if row.event == "sx.on_demand_requested"
        ],
        "full_report_requested": any(row.event == "sx.full_report_requested" for row in events),
        "reanalyse_requested": any(row.event == "sx.reanalyse_requested" for row in events),
        "first_open_seconds": first_open,
        "_first_open": opens[0] if opens else None,
    }


def daily_export(
    *,
    day: date,
    rows: Sequence[Row],
    export: Export | None,
    pads: tuple[bytes, bytes],
    environment: str,
    now: datetime,
) -> dict[str, Any]:
    """The day's export (pure: the caller reads the rows, the store and the pads)."""
    inner, outer = pads
    start, end = day_window(day)
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "environment": environment,
        "day": day.isoformat(),
        "generated_at": now.isoformat(),
        "ai_level_known": False,
    }
    by_ref: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        ref = row.payload.get("call_ref")
        if isinstance(ref, str):
            by_ref[ref].append(row)

    calls_out: list[dict[str, Any]] = []
    if export is not None:
        calls = {call.id: call for call in export.calls if call.kind not in TEST_KINDS}
        cost: dict[str, int] = defaultdict(int)
        report_cost: dict[str, int] = defaultdict(int)
        first_c2: dict[str, Any] = {}
        for step in export.steps:
            if step.call is None or step.call not in calls:
                continue
            cost[step.call] += step.paise or 0
            if step.stage == "C5":
                report_cost[step.call] += step.paise or 0
            if step.stage == "C2" and step.status == "succeeded":
                known = first_c2.get(step.call)
                if known is None or step.at < known.at:
                    first_c2[step.call] = step
        for call_id, step in sorted(first_c2.items(), key=lambda pair: pair[1].at):
            if india_day(step.at) != day:
                continue
            call = calls[call_id]
            ref = call_ref(inner, outer, call_id)
            usage = _call_usage(by_ref.get(ref, []), call.report_at)
            first_open = usage.pop("_first_open")
            calls_out.append(
                {
                    "call_ref": ref,
                    "workspace_ref": (
                        workspace_ref(inner, outer, call.company) if call.company else None
                    ),
                    "seller": call.person,
                    "length_band": length_band(step.audio_ms / 60_000),
                    "ai_level": None,
                    "version": version_id(call.version),
                    "cost_paise": cost[call_id],
                    "c5_paise": report_cost[call_id],
                    "full_report": call.report_at is not None,
                    **usage,
                    "opened_within_24h": first_open is not None
                    and first_open - step.at <= timedelta(hours=24),
                }
            )

    # The day's own events, per workspace.
    workspaces: dict[str, dict[str, Counter[Any]]] = defaultdict(
        lambda: {key: Counter() for key in ("reads", "actions", "on_demand", "full_report")}
    )
    for row in rows:
        if not start <= row.at < end:
            continue
        payload = row.payload
        groups = workspaces[workspace_ref(inner, outer, row.workspace)]
        if row.event == "sx.section_read":
            groups["reads"][
                (payload.get("section"), payload.get("read_band"), payload.get("look"))
            ] += 1
        elif row.event == "sx.section_action":
            groups["actions"][(payload.get("section"), payload.get("action"))] += 1
        elif row.event == "sx.on_demand_requested":
            groups["on_demand"][(payload.get("section"), payload.get("level"))] += 1
        elif row.event == "sx.full_report_requested":
            groups["full_report"][(payload.get("surface"), payload.get("level"))] += 1
    tallies: dict[str, Counter[str]] = defaultdict(Counter)
    for item in calls_out:
        key = item["workspace_ref"] or "unknown"
        tallies[key]["analysed"] += 1
        tallies[key]["opened"] += 1 if item["opened"] else 0
        tallies[key]["opened_within_24h"] += 1 if item["opened_within_24h"] else 0

    def rows_of(counter: Mapping[Any, int], names: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {**dict(zip(names, key, strict=True)), "count": count}
            for key, count in sorted(counter.items(), key=lambda pair: -pair[1])
        ]

    workspaces_out = []
    for ref in sorted(set(workspaces) | set(tallies)):
        groups = workspaces.get(ref) or {
            key: Counter() for key in ("reads", "actions", "on_demand", "full_report")
        }
        workspaces_out.append(
            {
                "workspace_ref": ref,
                "analysed": tallies[ref]["analysed"],
                "opened": tallies[ref]["opened"],
                "opened_within_24h": tallies[ref]["opened_within_24h"],
                "reads": rows_of(groups["reads"], ("section", "read_band", "look")),
                "actions": rows_of(groups["actions"], ("section", "action")),
                "on_demand": rows_of(groups["on_demand"], ("section", "level")),
                "full_report": rows_of(groups["full_report"], ("surface", "level")),
            }
        )
    return {
        **base,
        "cost_store": export is not None,
        "calls": calls_out,
        "workspaces": workspaces_out,
    }


__all__ = ["FOLLOW", "SCHEMA", "daily_export", "day_window", "length_band", "workspace_ref"]

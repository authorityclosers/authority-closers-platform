"""Cost per audio minute, now (owner, 22 Oct 2026: "is there any live meter single where we
can see internally the current cost per min?").

One environment's calls (production unless asked), from the same metrics store and engine as
Usage & cost, over today (India time), the last 24 hours and the last 7 days:

- A call counts in a window by when it was first transcribed, as Usage's cost per audio minute
  does: every step of that call (re-runs, pointer review, call data) over its audio minutes.
- Full reports: calls with a report. Short or data-only: transcribed, no report. All-in: both.
  Not analysed: recorded and audio-checked only (no transcription, no cost); counted apart and
  never in a rate.
- By version: the last 7 days' calls grouped by pipeline version, so a switch (one-pass, a
  new model) shows on its own instead of mixed into the old calls.
- Canary, QA and synthetic calls never count.

Money is list-price estimates at the rate the caller chose (each day's ECB rate, or the
planning rate); nothing here is an invoice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, time, timedelta
from typing import Any

from ac_platform.conversation_intelligence.application import ConversationError, utc
from ac_platform.conversation_intelligence.cost_metrics import (
    ENVIRONMENTS,
    FX,
    FX_MODES,
    INDIA,
    TEST_KINDS,
    AdminCostMetrics,
    Call,
    Export,
    Step,
    at_daily_rates,
    india_day,
    read_store,
    version_id,
    version_label,
)
from ac_platform.fx.store import REFRESHER
from ac_platform.kernel.authz import ActorContext

# The owner's two lines: the 21 Oct goal and the research target.
TARGETS = (0.40, 0.10)
WINDOWS = (("today", "Today"), ("24h", "Last 24 hours"), ("7d", "Last 7 days"))


def _per_minute(paise: int, audio_ms: int) -> float | None:
    return None if audio_ms <= 0 else round(paise / 100 / (audio_ms / 60_000), 3)


def _group(ids: Iterable[str], cost: Mapping[str, int], audio: Mapping[str, int]) -> dict[str, Any]:
    chosen = list(ids)
    paise = sum(cost[item] for item in chosen)
    audio_ms = sum(audio[item] for item in chosen)
    return {
        "calls": len(chosen),
        "audio_minutes": round(audio_ms / 60_000, 1),
        "rupees": round(paise / 100, 2),
        "per_minute": _per_minute(paise, audio_ms),
    }


def meter_view(exports: Sequence[Export], *, environment: str, now: datetime) -> dict[str, Any]:
    """The meter for one environment's export (pure: the caller reads the store and rates)."""
    export = next((item for item in exports if item.environment == environment), None)
    base: dict[str, Any] = {"environment": environment, "targets": list(TARGETS)}
    if export is None:
        return {**base, "available": False, "generated_at": None, "age_seconds": None}
    calls: dict[str, Call] = {call.id: call for call in export.calls if call.kind not in TEST_KINDS}
    cost: dict[str, int] = defaultdict(int)
    first: dict[str, Step] = {}
    for step in export.steps:
        if step.call is None or step.call not in calls:
            continue
        cost[step.call] += step.paise or 0
        if step.stage == "C2" and step.status == "succeeded":
            known = first.get(step.call)
            if known is None or step.at < known.at:
                first[step.call] = step
    audio = {call_id: step.audio_ms for call_id, step in first.items()}
    starts = {
        "today": datetime.combine(india_day(now), time.min, tzinfo=INDIA),
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
    }
    windows = []
    for key, label in WINDOWS:
        since = starts[key]
        analysed = [call_id for call_id, step in first.items() if step.at >= since]
        full = [call_id for call_id in analysed if calls[call_id].report_at is not None]
        short = [call_id for call_id in analysed if calls[call_id].report_at is None]
        recorded = [
            call for call_id, call in calls.items() if call_id not in first and call.at >= since
        ]
        windows.append(
            {
                "key": key,
                "label": label,
                "since": since.isoformat(),
                "all_in": _group(analysed, cost, audio),
                "full_reports": _group(full, cost, audio),
                "short": _group(short, cost, audio),
                "not_analysed": {
                    "calls": len(recorded),
                    "audio_minutes": round(sum(call.audio_ms for call in recorded) / 60_000, 1),
                },
            }
        )
    by_version: dict[str, list[str]] = defaultdict(list)
    for call_id, step in first.items():
        if step.at >= starts["7d"]:
            by_version[version_id(calls[call_id].version)].append(call_id)
    versions = [
        {
            "id": key,
            "label": version_label(calls[ids[0]].version),
            **_group(ids, cost, audio),
            "full_reports": sum(1 for call_id in ids if calls[call_id].report_at is not None),
            "first_at": min(first[call_id].at for call_id in ids).isoformat(),
            "last_at": max(first[call_id].at for call_id in ids).isoformat(),
        }
        for key, ids in by_version.items()
    ]
    versions.sort(key=lambda row: row["last_at"], reverse=True)
    generated = export.generated_at
    return {
        **base,
        "available": True,
        "generated_at": None if generated is None else generated.isoformat(),
        "age_seconds": None
        if generated is None
        else max(0, int((now - generated).total_seconds())),
        "windows": windows,
        "by_version": versions,
    }


async def read_meter(
    service: AdminCostMetrics,
    actor: ActorContext,
    *,
    environment: str = "production",
    fx: str = "daily",
) -> dict[str, Any]:
    """The meter as Admin reads it: admitted like Usage, the same store and rates."""
    await service.admit(actor)
    if environment not in ENVIRONMENTS:
        raise ConversationError("Choose production, staging or development.")
    if fx not in FX_MODES:
        raise ConversationError("Choose daily or planning rates.")
    exports, problems = read_store(service.store_root)
    now = utc(service.application.clock())
    fx_view = dict(FX)
    if fx == "daily":
        rates = await REFRESHER.rates(service.application.database, now)
        exports, fx_view = at_daily_rates(exports, rates, now - timedelta(days=7))
        fx_view["problem"] = REFRESHER.problem
    return {
        **meter_view(exports, environment=environment, now=now),
        "fx": fx_view,
        "problems": [row for row in problems if row["environment"] in (environment, "all")],
    }

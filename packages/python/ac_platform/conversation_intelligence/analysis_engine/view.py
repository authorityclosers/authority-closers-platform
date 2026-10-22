"""Expected against actual cost per module, computed on read (adaptive analysis, phase 1).

For one environment's calls over the last ``days`` (counted, as the cost meter counts them, by
when each call was first transcribed; canary, QA and synthetic calls never count):

- every recorded step is matched to its registry module by stage, model and the call's fact
  prompt revision; the module's fit at the call's audio minutes is what the engine expected,
  and the metrics store's list-price paise (every attempt, re-runs included) is what happened;
- by module: calls, rupees expected against actual, tokens expected against actual, unpriced
  steps; steps no module covers are listed by stage and model, never guessed;
- every plan projected on this window's own call mix, beside the window's actual all-in rate.

Nothing is stored: the expected figure is recomputed from the registry on every read and
stamped with the registry's version and digest (the decision log is phase 2). Rupees are at
the planning rate, the rate the fits are in; nothing here is an invoice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.conversation_intelligence.application import ConversationError, utc
from ac_platform.conversation_intelligence.cost_metrics import (
    ENVIRONMENTS,
    FX,
    TEST_KINDS,
    AdminCostMetrics,
    Call,
    Export,
    Step,
    read_store,
)
from ac_platform.kernel.authz import ActorContext

# Call analysis only: AI replies and quote facts are Lead Desk work, not a call's analysis.
STAGES = ("C1", "C2", "C4", "C5", "PR", "CDF", "CDD")
MAX_DAYS = 30
# A module whose actual runs this far from its fit is flagged for a refit.
DRIFT = 0.25


def _rupees(paise: float) -> float:
    return round(paise / 100, 2)


def _ratio(actual: float, expected: float) -> float | None:
    return None if expected <= 0 else round(actual / expected, 3)


def engine_view(
    exports: Sequence[Export], *, environment: str, now: datetime, days: int = 7
) -> dict[str, Any]:
    """The engine page for one environment's export (pure: the caller reads the store)."""
    export = next((item for item in exports if item.environment == environment), None)
    since = now - timedelta(days=days)
    # The fits are at the planning rate; the store's paise are at the price sheet's rate.
    scale = float(FX["planning_usd_to_inr"]) / registry.PLANNING_FX
    base: dict[str, Any] = {
        "environment": environment,
        "registry": registry.describe(),
        "days": days,
        "since": since.isoformat(),
        "drift": DRIFT,
        "fx": dict(FX),
    }
    if export is None:
        return {**base, "available": False, "generated_at": None, "age_seconds": None}
    calls: dict[str, Call] = {call.id: call for call in export.calls if call.kind not in TEST_KINDS}
    first: dict[str, Step] = {}
    for step in export.steps:
        if step.call in calls and step.stage == "C2" and step.status == "succeeded":
            known = first.get(step.call)
            if known is None or step.at < known.at:
                first[step.call] = step
    window = {call_id: step for call_id, step in first.items() if step.at >= since}
    minutes = {call_id: step.audio_ms / 60_000 for call_id, step in window.items()}

    # (module or unmodelled key, call) -> what happened
    actual: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"paise": 0, "steps": 0, "unpriced": 0, "in": 0, "out": 0}
    )
    unmodelled: dict[str, dict[str, Any]] = {}
    analysed: set[str] = set()
    for step in export.steps:
        if step.call not in window or step.stage not in STAGES:
            continue
        if step.stage == "C4":
            analysed.add(step.call)
        found = registry.match(step.stage, step.model, calls[step.call].version[1])
        key = found.id if found else f"{step.stage}·{step.model or 'no model'}"
        if found is None:
            unmodelled.setdefault(key, {"stage": step.stage, "model": step.model})
        row = actual[(key, step.call)]
        row["steps"] += 1
        row["in"] += step.input_tokens
        row["out"] += step.output_tokens
        if step.paise is None:
            if step.status == "succeeded":
                row["unpriced"] += 1
        else:
            row["paise"] += step.paise

    grouped: dict[str, dict[str, Any]] = {}
    for (key, call_id), row in actual.items():
        group = grouped.setdefault(
            key,
            {
                "calls": 0,
                "steps": 0,
                "unpriced_steps": 0,
                "audio_ms": 0,
                "actual_paise": 0,
                "expected_paise": 0.0,
                "tokens": {"actual_in": 0, "actual_out": 0, "expected_in": 0, "expected_out": 0},
                "fit_tokens": False,
            },
        )
        group["calls"] += 1
        group["steps"] += row["steps"]
        group["unpriced_steps"] += row["unpriced"]
        group["audio_ms"] += window[call_id].audio_ms
        group["actual_paise"] += row["paise"]
        group["tokens"]["actual_in"] += row["in"]
        group["tokens"]["actual_out"] += row["out"]
        if key in unmodelled:
            continue
        fit = registry.module(key).fit
        group["expected_paise"] += fit.cost(minutes[call_id]) * 100 * scale
        tokens = fit.tokens(minutes[call_id])
        if tokens is not None:
            group["fit_tokens"] = True
            group["tokens"]["expected_in"] += tokens[0]
            group["tokens"]["expected_out"] += tokens[1]

    order = {item.id: index for index, item in enumerate(registry.MODULES)}
    modules = []
    for key, group in sorted(
        grouped.items(), key=lambda pair: (order.get(pair[0], len(order)), pair[0])
    ):
        known = key not in unmodelled
        ratio = _ratio(group["actual_paise"], group["expected_paise"]) if known else None
        tokens = group["tokens"]
        modules.append(
            {
                "id": key,
                "label": registry.module(key).label if known else None,
                "stage": registry.module(key).stage if known else unmodelled[key]["stage"],
                "model": None if known else unmodelled[key]["model"],
                "modelled": known,
                "calls": group["calls"],
                "steps": group["steps"],
                "unpriced_steps": group["unpriced_steps"],
                "audio_minutes": round(group["audio_ms"] / 60_000, 1),
                "actual_rupees": _rupees(group["actual_paise"]),
                "expected_rupees": _rupees(group["expected_paise"]) if known else None,
                "ratio": ratio,
                "drifting": ratio is not None and abs(ratio - 1) > DRIFT,
                "tokens": {
                    "actual_in": tokens["actual_in"],
                    "actual_out": tokens["actual_out"],
                    "expected_in": tokens["expected_in"] if group["fit_tokens"] else None,
                    "expected_out": tokens["expected_out"] if group["fit_tokens"] else None,
                    "ratio_in": _ratio(tokens["actual_in"], tokens["expected_in"])
                    if group["fit_tokens"]
                    else None,
                    "ratio_out": _ratio(tokens["actual_out"], tokens["expected_out"])
                    if group["fit_tokens"]
                    else None,
                },
            }
        )

    total_ms = sum(step.audio_ms for step in window.values())
    actual_paise = sum(row["actual_paise"] for row in grouped.values())
    expected_paise = sum(row["expected_paise"] for row in grouped.values())
    mix = [(1, value) for value in minutes.values()]
    plans = [
        {
            "id": item.id,
            "label": item.label,
            "status": item.status,
            "window": registry.project(item, mix),
        }
        for item in registry.PLANS
    ]
    generated = export.generated_at
    return {
        **base,
        "available": True,
        "generated_at": None if generated is None else generated.isoformat(),
        "age_seconds": None
        if generated is None
        else max(0, int((now - generated).total_seconds())),
        "window": {
            "calls": len(window),
            "analysed": len(analysed),
            "short": len(window) - len(analysed),
            "audio_minutes": round(total_ms / 60_000, 1),
            "actual_rupees": _rupees(actual_paise),
            "expected_rupees": _rupees(expected_paise),
            "actual_per_minute": None
            if total_ms <= 0
            else round(actual_paise / 100 / (total_ms / 60_000), 3),
            "expected_per_minute": None
            if total_ms <= 0
            else round(expected_paise / 100 / (total_ms / 60_000), 3),
        },
        "modules": modules,
        "plans": plans,
    }


async def read_engine(
    service: AdminCostMetrics,
    actor: ActorContext,
    *,
    environment: str = "production",
    days: int = 7,
) -> dict[str, Any]:
    """The engine page as Admin reads it: admitted like Usage, the same store, planning rate."""
    await service.admit(actor)
    if environment not in ENVIRONMENTS:
        raise ConversationError("Choose production, staging or development.")
    if not 1 <= days <= MAX_DAYS:
        raise ConversationError(f"Choose 1 to {MAX_DAYS} days.")
    exports, problems = read_store(service.store_root)
    now = utc(service.application.clock())
    return {
        **engine_view(exports, environment=environment, now=now, days=days),
        "problems": [row for row in problems if row["environment"] in (environment, "all")],
    }

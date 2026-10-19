"""Analysis health for the call data engine and Review 2.0 (admin revamp Phase 4, 19 Oct 2026).

Two read-only parts the Analysis health summary adds for its window:

- ``engine``: per pipeline (fast, deep), the runs that ended and how (succeeded,
  failed, skipped) with their stored reason codes, time and recorded cost; runs
  still going, and runs gone quiet (no outcome after QUIET_AFTER); the same
  outcomes per pipeline version and per day.
- ``review``: the gold reviewers' current answers, per review pipeline and
  question; how often the analysis was judged right, per item type and per
  engine version; and, where two reviewers answered the same claim, how often
  they agreed.

A verdict question's first option is the "right" answer and its second the
"wrong" one (correct/wrong, true/false); other options (unsure) count as
answers but not toward the share. Codes, counts, times and costs only: no call
text, and no correction text.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import utc
from ac_platform.conversation_intelligence.review_models import ReviewVerdict
from ac_platform.conversation_intelligence.review_verdicts import ReviewVerdicts
from ac_platform.identity.models import Person

ENGINE_PIPELINES = ("fast", "deep")
OUTCOMES = ("succeeded", "failed", "skipped")
QUIET_AFTER = timedelta(minutes=30)
MAX_RUNS = 20_000
MAX_VERDICTS = 20_000
MAX_VERSIONS = 20
TOP = 12
OBJECT_TARGETS = ("object", "fact")
_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,119}$")


def _code(value: str | None) -> str:
    if not value:
        return "not_recorded"
    return value if _CODE.fullmatch(value) else "withheld"


def _times(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"count": 0, "p50_ms": None, "p90_ms": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": round(median(ordered)),
        "p90_ms": ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))],
    }


def _share(part: int, whole: int) -> float | None:
    return None if whole <= 0 else round(part / whole, 3)


def _inr(value: Decimal) -> float:
    return float(round(value, 2))


def _tally() -> dict[str, Any]:
    return {
        "states": Counter(),
        "ms": [],
        "cost": Decimal(0),
        "calls": set(),
        "reasons": Counter(),
        "models": Counter(),
        "running": 0,
        "quiet": 0,
        "newest": None,
        "version": None,
    }


def _ended(tally: dict[str, Any]) -> dict[str, Any]:
    states: Counter[str] = tally["states"]
    charged = states["succeeded"] + states["failed"]
    return {
        "runs": sum(states[state] for state in OUTCOMES),
        **{state: states[state] for state in OUTCOMES},
        "success_share": _share(states["succeeded"], charged),
        "time": _times(tally["ms"]),
        "cost_inr": _inr(tally["cost"]),
        "cost_per_run_inr": None if charged == 0 else _inr(tally["cost"] / charged),
    }


def run_health(rows: Sequence[Any], *, now: datetime, since: datetime) -> dict[str, Any]:
    """Engine runs in a window, per pipeline, per pipeline version and per day.

    A run is a 'running' row and then its outcome row, which supersedes it; a
    skip is an outcome row alone. A running row with no outcome is still going,
    or gone quiet once it is older than QUIET_AFTER.
    """

    now = utc(now)
    ended = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    pipelines: dict[str, dict[str, Any]] = {name: _tally() for name in ENGINE_PIPELINES}
    versions: dict[tuple[str, str], dict[str, Any]] = {}
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    quiet: list[dict[str, Any]] = []
    for row in rows:
        at = utc(row.created_at)
        tally = pipelines.setdefault(row.pipeline, _tally())
        if row.state == "running":
            if row.id in ended:
                continue
            if now - at > QUIET_AFTER:
                tally["quiet"] += 1
                quiet.append(
                    {
                        "run_id": str(row.id),
                        "recording_id": str(row.recording_id),
                        "pipeline": row.pipeline,
                        "started_at": at.isoformat(),
                    }
                )
            else:
                tally["running"] += 1
            continue
        if row.state not in OUTCOMES:
            continue
        version = versions.setdefault((row.pipeline, row.pipeline_version), _tally())
        for group in (tally, version):
            group["states"][row.state] += 1
            if group["newest"] is None or at > group["newest"]:
                group["newest"], group["version"] = at, row.pipeline_version
            if row.cost_inr is not None:
                group["cost"] += Decimal(row.cost_inr)
            if row.state == "succeeded":
                group["calls"].add(row.recording_id)
                if isinstance(row.duration_ms, int) and row.duration_ms >= 0:
                    group["ms"].append(row.duration_ms)
        if row.state != "succeeded":
            tally["reasons"][(row.state, _code(row.reason_code))] += 1
        if row.model_id:
            tally["models"][(row.provider, row.model_id)] += 1
        daily[at.date().isoformat()][f"{row.pipeline}:{row.state}"] += 1

    def pipeline_view(name: str, tally: dict[str, Any]) -> dict[str, Any]:
        return {
            "pipeline": name,
            "version": tally["version"],
            **_ended(tally),
            "calls": len(tally["calls"]),
            "running": tally["running"],
            "quiet": tally["quiet"],
            # Most runs first; on a tie, failures before skips, then by code.
            "reasons": [
                {"state": state, "code": code, "runs": runs}
                for (state, code), runs in sorted(
                    tally["reasons"].items(),
                    key=lambda item: (-item[1], item[0][0] != "failed", item[0][1]),
                )[:TOP]
            ],
            "models": [
                {"provider": provider, "model": model, "runs": runs}
                for (provider, model), runs in tally["models"].most_common(TOP)
            ],
        }

    order = {name: index for index, name in enumerate(ENGINE_PIPELINES)}
    version_rows = [
        {
            "pipeline": pipeline,
            "version": version,
            **_ended(tally),
            "last_at": tally["newest"].isoformat(),
        }
        for (pipeline, version), tally in versions.items()
    ]
    # Pipelines in order, newest version first within each.
    version_rows.sort(key=lambda row: row["last_at"], reverse=True)
    version_rows.sort(key=lambda row: order.get(row["pipeline"], len(order)))
    names = sorted(pipelines, key=lambda name: (order.get(name, len(order)), name))
    days = []
    for offset in range((now.date() - utc(since).date()).days, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        days.append(
            {
                "day": day,
                **{
                    name: {
                        "succeeded": daily[day][f"{name}:succeeded"],
                        "failed": daily[day][f"{name}:failed"],
                    }
                    for name in names
                },
            }
        )
    quiet.sort(key=lambda item: item["started_at"])
    return {
        "pipelines": [pipeline_view(name, pipelines[name]) for name in names],
        "versions": version_rows[:MAX_VERSIONS],
        "daily": days,
        "quiet": quiet[:20],
    }


def _main_question(definition: Mapping[str, Any]) -> dict[str, Any] | None:
    for question in definition.get("questions", []):
        if isinstance(question, dict) and question.get("kind") == "verdict":
            return question
    return None


def _target_type(row: Any, objects: Mapping[UUID, Any]) -> str:
    if row.target_kind == "coaching":
        _, _, key = row.target_ref.partition(":")
        return "coaching." + (key.split(":")[0] or "point")
    try:
        found = objects.get(UUID(row.target_ref))
    except ValueError:
        found = None
    return found.type_key if found is not None else "unknown"


def _type_row(name: str, counts: Counter[str]) -> dict[str, Any]:
    return {
        "type": name,
        "answers": sum(counts.values()),
        "right": counts["right"],
        "wrong": counts["wrong"],
        "right_share": _share(counts["right"], counts["right"] + counts["wrong"]),
    }


def review_measures(
    verdicts: Sequence[Any],
    pipelines: Mapping[str, Mapping[str, Any]],
    objects: Mapping[UUID, Any],
    names: Mapping[UUID, str],
) -> dict[str, Any]:
    """Current answers (not superseded, not erased) measured per pipeline, type and version."""

    by_pipeline: dict[str, list[Any]] = defaultdict(list)
    for row in verdicts:
        by_pipeline[row.pipeline_key].append(row)
    keys = list(pipelines) + sorted(set(by_pipeline) - set(pipelines))
    engine_versions: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    views = []
    for key in keys:
        rows = by_pipeline.get(key, [])
        definition = pipelines.get(key, {}).get("definition", {})
        definition = definition if isinstance(definition, Mapping) else {}
        main = _main_question(definition)
        options = [str(option) for option in (main or {}).get("options", [])]
        right = options[0] if options else None
        wrong = options[1] if len(options) > 1 else None

        questions = []
        for question in definition.get("questions", []):
            if not isinstance(question, dict):
                continue
            answered = [row for row in rows if row.question_key == question.get("key")]
            values = [(row.answer or {}).get("value") for row in answered]
            view: dict[str, Any] = {
                "key": question.get("key"),
                "label": question.get("label"),
                "kind": question.get("kind"),
                "answers": len(answered),
            }
            if question.get("kind") in ("verdict", "pick"):
                view["counts"] = {
                    str(option): sum(1 for value in values if value == option)
                    for option in question.get("options", [])
                }
            if question.get("kind") == "scale":
                scores = [value for value in values if isinstance(value, int)]
                view["average"] = round(sum(scores) / len(scores), 2) if scores else None
            questions.append(view)

        judged = [row for row in rows if main is not None and row.question_key == main["key"]]
        types: dict[str, Counter[str]] = defaultdict(Counter)
        claims: dict[tuple[str, str, str], dict[UUID, Any]] = defaultdict(dict)
        for row in judged:
            value = (row.answer or {}).get("value")
            outcome = "right" if value == right else "wrong" if value == wrong else "other"
            types[_target_type(row, objects)][outcome] += 1
            claims[(row.target_kind, row.target_ref, row.ai_sha256)][row.reviewer_id] = value
            if row.target_kind in OBJECT_TARGETS:
                try:
                    found = objects.get(UUID(row.target_ref))
                except ValueError:
                    found = None
                if found is not None:
                    engine_versions[(found.pipeline, found.pipeline_version)][outcome] += 1
        compared = [answers for answers in claims.values() if len(answers) >= 2]
        agreed = sum(1 for answers in compared if len(set(answers.values())) == 1)
        right_total = sum(counts["right"] for counts in types.values())
        wrong_total = sum(counts["wrong"] for counts in types.values())
        views.append(
            {
                "key": key,
                "title": pipelines.get(key, {}).get("title", key),
                "kind": pipelines.get(key, {}).get("kind"),
                "answers": len(rows),
                "calls": len({row.recording_id for row in rows}),
                "items": len({(row.target_kind, row.target_ref) for row in rows}),
                "reviewers": len({row.reviewer_id for row in rows}),
                "main_question": None if main is None else main["key"],
                "right": right_total,
                "wrong": wrong_total,
                "right_share": _share(right_total, right_total + wrong_total),
                "questions": questions,
                "types": sorted(
                    (_type_row(name, counts) for name, counts in types.items()),
                    key=lambda item: (-item["answers"], item["type"]),
                )[:TOP],
                "agreement": {
                    "compared": len(compared),
                    "agreed": agreed,
                    "share": _share(agreed, len(compared)),
                },
            }
        )

    reviewers: dict[UUID, dict[str, Any]] = {}
    for row in verdicts:
        entry = reviewers.setdefault(row.reviewer_id, {"answers": 0, "calls": set()})
        entry["answers"] += 1
        entry["calls"].add(row.recording_id)
    return {
        "answers": len(verdicts),
        "calls": len({row.recording_id for row in verdicts}),
        "pipelines": views,
        "engine_versions": sorted(
            (
                {
                    "pipeline": pipeline,
                    "version": version,
                    "answers": sum(counts.values()),
                    "right_share": _share(counts["right"], counts["right"] + counts["wrong"]),
                }
                for (pipeline, version), counts in engine_versions.items()
            ),
            key=lambda item: (item["pipeline"], item["version"]),
        ),
        "reviewers": sorted(
            (
                {
                    "name": names.get(person, "Reviewer"),
                    "answers": entry["answers"],
                    "calls": len(entry["calls"]),
                }
                for person, entry in reviewers.items()
            ),
            key=lambda item: (-item["answers"], item["name"]),
        ),
    }


async def engine_health(
    database: AsyncSession, scope: Sequence[UUID], *, since: datetime, now: datetime
) -> dict[str, Any]:
    """The call data engine's runs for the served organisations in the window."""

    from ac_platform.call_data.models import CallDataRun

    rows = list(
        (
            await database.scalars(
                select(CallDataRun)
                .where(CallDataRun.tenant_id.in_(tuple(scope)), CallDataRun.created_at >= since)
                .order_by(CallDataRun.created_at.desc())
                .limit(MAX_RUNS + 1)
            )
        ).all()
    )
    return {
        **run_health(rows[:MAX_RUNS], now=now, since=since),
        "truncated": len(rows) > MAX_RUNS,
    }


async def review_health(
    database: AsyncSession,
    operations_tenant_id: UUID,
    scope: Sequence[UUID],
    *,
    since: datetime,
) -> dict[str, Any]:
    """Review 2.0 answers given in the window on the served organisations' calls."""

    from ac_platform.call_data.models import CallObject

    rows = list(
        (
            await database.scalars(
                select(ReviewVerdict)
                .where(ReviewVerdict.tenant_id.in_(tuple(scope)), ReviewVerdict.created_at >= since)
                .order_by(ReviewVerdict.created_at.desc())
                .limit(MAX_VERDICTS + 1)
            )
        ).all()
    )
    truncated = len(rows) > MAX_VERDICTS
    rows = rows[:MAX_VERDICTS]
    replaced = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    current = [
        row
        for row in rows
        if row.id not in replaced and row.erased_at is None and row.answer is not None
    ]
    refs: set[UUID] = set()
    for row in current:
        if row.target_kind in OBJECT_TARGETS:
            try:
                refs.add(UUID(row.target_ref))
            except ValueError:
                continue
    objects = (
        {
            item.id: item
            for item in (
                await database.scalars(select(CallObject).where(CallObject.id.in_(refs)))
            ).all()
        }
        if refs
        else {}
    )
    people = {row.reviewer_id for row in current}
    names = (
        {
            person_id: name
            for person_id, name in (
                await database.execute(
                    select(Person.id, Person.display_name).where(Person.id.in_(people))
                )
            ).tuples()
            if name
        }
        if people
        else {}
    )
    pipelines = await ReviewVerdicts(database, operations_tenant_id).pipelines()
    return {**review_measures(current, pipelines, objects, names), "truncated": truncated}

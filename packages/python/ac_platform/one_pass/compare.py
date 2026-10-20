"""Side by side: today's pipeline (classic) and the one-pass pipeline on the same call.

Per call: cost, tokens and time per stage; the transcripts; the facts (call objects
matched by type and wording); the 27 pointer scores; the coaching points and the eight
dimensions; and which of the six contracts the one-pass answer passed. Across calls: the
same, summed and averaged, for real calls and the fictional benchmark set apart.

Classic for a real call is read from today's own tables (the call map's costs and times,
the C2 transcript, C4 packets, the report draft, the pointer review, current call
objects); nothing is copied. Classic for a fictional benchmark call is the research's
result, imported as a benchmark row. Read-only. The per-call view shows call content
and is for Admin only (the route audits it); the summary is numbers only.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from ac_platform.call_data import taxonomy
from ac_platform.call_data.values import similar
from ac_platform.one_pass import pricing

SCHEMA: Final = "one-pass-compare/1"
CONTRACTS: Final = ("c2", "c4", "c5", "pointer_review", "call_objects", "prospect_facts")
_WORD = re.compile(r"\w+", re.UNICODE)
CLASSIC_STAGES: Final[dict[str, str]] = {
    "transcription": "Transcription (Scribe)",
    "facts": "C4 facts",
    "coaching": "C5 report and coaching",
    "pointer_review": "Pointer review",
    "fast": "Call data: fast",
    "deep": "Call data: deep",
}


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _words(segments: Iterable[Mapping[str, Any]]) -> list[str]:
    return [w.casefold() for s in segments for w in _WORD.findall(str(s.get("text") or ""))]


def transcript_view(transcript: Mapping[str, Any] | None, source: str) -> dict[str, Any] | None:
    if not isinstance(transcript, Mapping):
        return None
    segments = [s for s in transcript.get("segments") or [] if isinstance(s, Mapping)]
    return {
        "source": source,
        "segments": len(segments),
        "speakers": len({s.get("speaker_id") for s in segments}),
        "words": len(_words(segments)),
        "rows": [
            {
                "id": s.get("id"),
                "speaker": s.get("speaker_id"),
                "start_ms": s.get("start_ms"),
                "text": s.get("text"),
            }
            for s in segments
        ],
    }


def _objects(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        key = str(row.get("type_key") or row.get("type") or "")
        kind_type = taxonomy.get(key)
        if kind_type is None or kind_type.kind in ("segment", "audio"):
            continue
        result.append(
            {
                "type": key,
                "label": kind_type.label,
                "display": str(row.get("display") or ""),
                "confidence": _float(row.get("confidence")),
                "basis": row.get("basis"),
                "pipeline": row.get("pipeline"),
            }
        )
    return sorted(result, key=lambda o: (taxonomy.TYPES[o["type"]].priority, o["display"]))


def _pointers(review: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(review, Mapping) or not isinstance(review.get("pointers"), list):
        return None
    found = review.get("overall")
    overall: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    return {
        "overall": overall.get("score"),
        "line": overall.get("line"),
        "rows": [
            {
                "id": p.get("id"),
                "label": p.get("label"),
                "status": p.get("status"),
                "score": p.get("score"),
                "what_happened": p.get("what_happened"),
            }
            for p in review["pointers"]
            if isinstance(p, Mapping)
        ],
    }


def _titles(items: Any) -> list[str]:
    return [
        str(item.get("title"))
        for item in items or []
        if isinstance(item, Mapping) and item.get("title")
    ]


def _coaching(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, Mapping):
        return None
    return {
        "summary": report.get("summary"),
        "verdict": report.get("verdict"),
        "strengths": _titles(report.get("strengths")),
        "improvements": _titles(report.get("improvements")),
        "missed_opportunities": _titles(report.get("missed_opportunities")),
        "objections": _titles(report.get("objection_analysis")),
        "closing": _titles(report.get("closing_analysis")),
        "dimensions": [
            {"id": d.get("dimension_id"), "status": d.get("status")}
            for d in report.get("dimensions") or []
            if isinstance(d, Mapping)
        ],
    }


def _stage(
    key: str,
    label: str,
    *,
    inr: Any = None,
    tokens_in: Any = None,
    tokens_out: Any = None,
    ms: Any = None,
    model: Any = None,
    tier: Any = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "inr": _float(inr),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "ms": ms,
        "model": model,
        "tier": tier,
        "note": note,
    }


def _totals(side: dict[str, Any]) -> dict[str, Any]:
    stages = side["stages"]
    priced = [s["inr"] for s in stages if s["inr"] is not None]
    total = round(sum(priced), 4) if priced else None
    side["cost_inr"] = total
    side["per_minute_inr"] = pricing.per_minute(total, side.get("audio_ms"))
    side["tokens_in"] = sum(s["tokens_in"] or 0 for s in stages)
    side["tokens_out"] = sum(s["tokens_out"] or 0 for s in stages)
    return side


# ----- the one-pass side (and benchmark classic rows) ---------------------------------


def side_from_row(row: Any) -> dict[str, Any]:
    """A stored run (one-pass, or a benchmark call's imported classic result)."""
    outputs: Mapping[str, Any] = row.outputs if isinstance(row.outputs, Mapping) else {}
    usage: Mapping[str, Any] = row.usage if isinstance(row.usage, Mapping) else {}
    flex: list[float | None] = []
    standard: list[float | None] = []
    if row.pipeline == "classic":
        stages = [
            _stage(
                str(s.get("key", "")),
                str(s.get("label") or CLASSIC_STAGES.get(str(s.get("key", "")), s.get("key", ""))),
                inr=s.get("inr"),
                tokens_in=s.get("tokens_in"),
                tokens_out=s.get("tokens_out"),
                ms=s.get("ms"),
                model=s.get("model"),
                note=s.get("note"),
            )
            for s in usage.get("stages") or []
            if isinstance(s, Mapping)
        ]
        source = "Fictional script (perfect transcript)"
    else:
        heard: Mapping[str, Any] = usage.get("transcription") or {}
        read: Mapping[str, Any] = usage.get("analysis") or {}
        stages = [
            _stage(
                "transcription",
                "Transcription (Gemini 3.1 Flash-Lite)",
                inr=row.transcription_cost_inr,
                tokens_in=row.transcription_input_tokens,
                tokens_out=row.transcription_output_tokens,
                ms=row.transcription_ms,
                model=row.transcription_model,
                tier=row.transcription_tier,
            ),
            _stage(
                "analysis",
                "One pass (Gemini 3.8 Flash)",
                inr=row.analysis_cost_inr,
                tokens_in=row.analysis_input_tokens,
                tokens_out=row.analysis_output_tokens,
                ms=row.analysis_ms,
                model=row.analysis_model,
                tier=row.analysis_tier,
                note=(
                    f"{row.analysis_cached_tokens} input tokens from the cache"
                    if row.analysis_cached_tokens
                    else None
                ),
            ),
        ]
        source = "Gemini 3.1 Flash-Lite"
        flex = [_float(part.get("flex_inr")) for part in (heard, read)]
        standard = [_float(part.get("standard_inr")) for part in (heard, read)]
    side: dict[str, Any] = {
        "pipeline": row.pipeline,
        "available": row.state == "succeeded",
        "state": row.state,
        "reason": row.reason_code,
        "run_id": str(row.id),
        "at": row.created_at.isoformat(),
        "audio_ms": row.audio_ms,
        "stages": stages,
        "duration_ms": row.duration_ms,
        "transcript": transcript_view(row.transcript, source),
        "objects": _objects(outputs.get("call_objects") or []),
        "c4_observations": len(((outputs.get("c4") or {}).get("observations")) or [])
        if isinstance(outputs.get("c4"), Mapping)
        else outputs.get("c4_observation_count"),
        "pointers": _pointers(outputs.get("pointer_review")),
        "coaching": _coaching(outputs.get("c5")),
        "checks": row.checks if row.pipeline == "one_pass" else None,
        "judge": outputs.get("judge"),
    }
    _totals(side)
    if row.pipeline == "one_pass" and all(v is not None for v in flex + standard):
        side["flex_cost_inr"] = round(sum(v for v in flex if v is not None), 4)
        side["standard_cost_inr"] = round(sum(v for v in standard if v is not None), 4)
        side["flex_per_minute_inr"] = pricing.per_minute(side["flex_cost_inr"], row.audio_ms)
        side["standard_per_minute_inr"] = pricing.per_minute(
            side["standard_cost_inr"], row.audio_ms
        )
    return side


# ----- the classic side of a real call, from today's tables -----------------------------


def classic_from_call(connection: Any, recording_id: UUID) -> dict[str, Any] | None:
    from ac_platform.call_data.call_map import call_map

    mapped = call_map(connection, recording_id)
    if mapped is None:
        return None
    by_key = {stage["key"]: stage for stage in mapped["stages"]}
    stages = []
    for key, label in CLASSIC_STAGES.items():
        stage = by_key.get(key)
        if stage is None or stage["status"] in ("waiting", "not_built"):
            continue
        counts = stage.get("counts") or {}
        stages.append(
            _stage(
                key,
                label,
                inr=stage.get("cost_inr"),
                tokens_in=counts.get("tokens_in"),
                tokens_out=counts.get("tokens_out"),
                ms=stage.get("duration_ms"),
                model=stage.get("model"),
                note=None if stage["status"] == "done" else stage["status"],
            )
        )
    transcript = connection.execute(
        text(
            "SELECT payload FROM conversation_checkpoints WHERE recording_id = :r"
            " AND stage = 'C2' AND erased_at IS NULL ORDER BY created_at DESC LIMIT 1"
        ),
        {"r": recording_id},
    ).scalar()
    revision = transcript.get("revision") if isinstance(transcript, Mapping) else None
    observations = connection.execute(
        text(
            "SELECT coalesce(sum(json_array_length(payload -> 'observations')), 0)"
            " FROM conversation_checkpoints WHERE recording_id = :r AND stage = 'C4'"
            " AND erased_at IS NULL AND payload ->> 'transcript_revision' = :revision"
        ),
        {"r": recording_id, "revision": revision},
    ).scalar()
    report = connection.execute(
        text(
            "SELECT payload FROM conversation_report_drafts WHERE recording_id = :r"
            " AND erased_at IS NULL ORDER BY created_at DESC LIMIT 1"
        ),
        {"r": recording_id},
    ).scalar()
    review = connection.execute(
        text(
            "SELECT payload FROM conversation_pointer_reviews WHERE recording_id = :r"
            " AND erased_at IS NULL ORDER BY created_at DESC LIMIT 1"
        ),
        {"r": recording_id},
    ).scalar()
    objects = connection.execute(
        text(
            """
            SELECT o.type_key, o.display, o.confidence, o.basis, o.pipeline
            FROM call_objects o
            WHERE o.recording_id = :r AND o.erased_at IS NULL AND NOT o.retracted
              AND NOT EXISTS (SELECT 1 FROM call_objects n WHERE n.supersedes_id = o.id)
            """
        ),
        {"r": recording_id},
    ).mappings()
    published = by_key.get("published") or {}
    started = by_key.get("transcription") or {}
    side: dict[str, Any] = {
        "pipeline": "classic",
        "available": published.get("status") == "done",
        "state": published.get("status"),
        "reason": None,
        "run_id": None,
        "at": published.get("finished_at"),
        "audio_ms": mapped.get("media_ms"),
        "stages": stages,
        "duration_ms": _span_ms(started.get("started_at"), published.get("finished_at")),
        "transcript": transcript_view(transcript, "ElevenLabs Scribe"),
        "objects": _objects(objects),
        "c4_observations": int(observations or 0),
        "pointers": _pointers(review),
        "coaching": _coaching(report),
        "checks": None,
        "judge": None,
    }
    if side["audio_ms"] is None and isinstance(transcript, Mapping):
        ends = [s.get("end_ms") for s in transcript.get("segments") or [] if isinstance(s, Mapping)]
        side["audio_ms"] = max((e for e in ends if isinstance(e, int)), default=None)
    return _totals(side)


def _span_ms(start: str | None, end: str | None) -> int | None:
    from datetime import datetime

    if not start or not end:
        return None
    return max(
        0,
        round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000),
    )


# ----- differences ------------------------------------------------------------------


def fact_diff(
    classic: Sequence[Mapping[str, Any]], one: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Facts matched by type and near-same wording."""
    left = list(classic)
    both, only_one = [], []
    for item in one:
        match = next(
            (
                c
                for c in left
                if c["type"] == item["type"] and similar(str(c["display"]), str(item["display"]))
            ),
            None,
        )
        if match is None:
            only_one.append(item)
        else:
            left.remove(match)
            both.append(
                {
                    "type": item["type"],
                    "label": item["label"],
                    "classic": match["display"],
                    "one_pass": item["display"],
                }
            )
    union = len(both) + len(left) + len(only_one)
    return {
        "both": both,
        "only_classic": left,
        "only_one_pass": only_one,
        "overlap": round(len(both) / union, 4) if union else None,
    }


_BAND = {"excellent": 4, "good": 3, "average": 2, "needs_improvement": 1}


def pointer_diff(
    classic: Mapping[str, Any] | None, one: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if not classic or not one:
        return None
    theirs = {row["id"]: row for row in one["rows"]}
    rows, same, judged, gaps = [], 0, 0, []
    for row in classic["rows"]:
        other = theirs.get(row["id"])
        if other is None:
            continue
        agree = row["status"] == other["status"]
        same += agree
        judged += 1
        if isinstance(row["score"], int) and isinstance(other["score"], int):
            gaps.append(abs(row["score"] - other["score"]))
        rows.append(
            {
                "id": row["id"],
                "label": row["label"],
                "classic": {"status": row["status"], "score": row["score"]},
                "one_pass": {"status": other["status"], "score": other["score"]},
                "same_status": agree,
            }
        )
    overall = (
        one["overall"] - classic["overall"]
        if isinstance(one["overall"], int) and isinstance(classic["overall"], int)
        else None
    )
    return {
        "rows": rows,
        "same_status": same,
        "compared": judged,
        "agreement": round(same / judged, 4) if judged else None,
        "mean_score_gap": round(statistics.fmean(gaps), 2) if gaps else None,
        "overall_difference": overall,
    }


def coaching_diff(
    classic: Mapping[str, Any] | None, one: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if not classic or not one:
        return None
    theirs = {d["id"]: d["status"] for d in one["dimensions"]}
    dimensions = [
        {"id": d["id"], "classic": d["status"], "one_pass": theirs.get(d["id"])}
        for d in classic["dimensions"]
    ]
    same = sum(1 for d in dimensions if d["classic"] == d["one_pass"])
    counts = {
        key: {"classic": len(classic[key]), "one_pass": len(one[key])}
        for key in ("strengths", "improvements", "missed_opportunities", "objections", "closing")
    }
    return {
        "counts": counts,
        "dimensions": dimensions,
        "dimension_agreement": round(same / len(dimensions), 4) if dimensions else None,
    }


def transcript_diff(
    classic: Mapping[str, Any] | None, one: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if not classic or not one:
        return None
    left = {w for row in classic["rows"] for w in _WORD.findall(str(row["text"] or "").casefold())}
    right = {w for row in one["rows"] for w in _WORD.findall(str(row["text"] or "").casefold())}
    union = left | right
    return {
        "word_ratio": round(one["words"] / classic["words"], 4) if classic["words"] else None,
        "vocabulary_overlap": round(len(left & right) / len(union), 4) if union else None,
        "speakers": {"classic": classic["speakers"], "one_pass": one["speakers"]},
    }


def compare(classic: dict[str, Any] | None, one: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": SCHEMA, "classic": classic, "one_pass": one}
    if classic is None or one is None:
        return result
    saving = (
        classic["cost_inr"] - one["cost_inr"]
        if classic["cost_inr"] is not None and one["cost_inr"] is not None
        else None
    )
    result["differences"] = {
        "cost_saving_inr": _float(saving),
        "cost_ratio": round(one["cost_inr"] / classic["cost_inr"], 4)
        if classic["cost_inr"] and one["cost_inr"] is not None
        else None,
        "time_ratio": round(one["duration_ms"] / classic["duration_ms"], 4)
        if classic["duration_ms"] and one["duration_ms"] is not None
        else None,
        "facts": fact_diff(classic["objects"], one["objects"]),
        "pointers": pointer_diff(classic["pointers"], one["pointers"]),
        "coaching": coaching_diff(classic["coaching"], one["coaching"]),
        "transcript": transcript_diff(classic["transcript"], one["transcript"]),
    }
    return result


# ----- reading runs -------------------------------------------------------------------

_LATEST = """
SELECT DISTINCT ON (coalesce(recording_id::text, bench_call), pipeline) *
FROM one_pass_runs
WHERE state <> 'running' {where}
ORDER BY coalesce(recording_id::text, bench_call), pipeline,
         (state = 'succeeded') DESC, created_at DESC
"""


def _latest(connection: Any, where: str = "", params: Mapping[str, Any] | None = None) -> list[Any]:
    return list(
        connection.execute(text(_LATEST.format(where=where)), dict(params or {}))  # noqa: S608
    )


def call_compare(
    connection: Any, *, recording_id: UUID | None = None, bench_call: str | None = None
) -> dict[str, Any] | None:
    if (recording_id is None) == (bench_call is None):
        raise ValueError("one subject")
    if recording_id is not None:
        rows = _latest(connection, "AND recording_id = :r", {"r": recording_id})
    else:
        rows = _latest(connection, "AND bench_call = :b", {"b": bench_call})
    one = next((side_from_row(r) for r in rows if r.pipeline == "one_pass"), None)
    if recording_id is not None:
        classic = classic_from_call(connection, recording_id)
    else:
        classic = next((side_from_row(r) for r in rows if r.pipeline == "classic"), None)
    if one is None and classic is None:
        return None
    result = compare(classic, one)
    result["subject"] = (
        {"kind": "call", "recording_id": str(recording_id)}
        if recording_id is not None
        else {"kind": "bench", "call": bench_call}
    )
    return result


def _mean(values: Iterable[float | None]) -> float | None:
    numbers = [v for v in values if v is not None]
    return round(statistics.fmean(numbers), 4) if numbers else None


def _median(values: Iterable[int | float | None]) -> float | None:
    numbers = [v for v in values if v is not None]
    return round(float(statistics.median(numbers)), 1) if numbers else None


def summarise(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Totals and averages over compared calls (each a ``compare`` result with both sides)."""
    pairs = [
        i for i in items if i.get("classic") and i.get("one_pass") and i["one_pass"]["available"]
    ]
    minutes = sum((i["one_pass"]["audio_ms"] or 0) for i in pairs) / 60_000

    def total(side: str, key: str = "cost_inr") -> float | None:
        values = [i[side].get(key) for i in pairs]
        return (
            round(sum(v for v in values if v is not None), 4)
            if values and all(v is not None for v in values)
            else None
        )

    classic_inr, one_inr = total("classic"), total("one_pass")
    flex_inr, standard_inr = (
        total("one_pass", "flex_cost_inr"),
        total("one_pass", "standard_cost_inr"),
    )
    checks = [i["one_pass"].get("checks") or {} for i in pairs]
    differences = [i.get("differences") or {} for i in pairs]
    judges = [(i["classic"].get("judge") or {}, i["one_pass"].get("judge") or {}) for i in pairs]
    return {
        "calls": len(pairs),
        "audio_minutes": round(minutes, 2),
        "classic": {
            "cost_inr": classic_inr,
            "per_minute_inr": round(classic_inr / minutes, 4)
            if classic_inr is not None and minutes
            else None,
            "median_ms": _median(i["classic"]["duration_ms"] for i in pairs),
            "fact_recall": _mean(c.get("fact_recall") for c, _ in judges),
            "truth_coverage": _mean(c.get("truth_coverage") for c, _ in judges),
        },
        "one_pass": {
            "cost_inr": one_inr,
            "per_minute_inr": round(one_inr / minutes, 4)
            if one_inr is not None and minutes
            else None,
            "standard_per_minute_inr": round(standard_inr / minutes, 4)
            if standard_inr is not None and minutes
            else None,
            "flex_per_minute_inr": round(flex_inr / minutes, 4)
            if flex_inr is not None and minutes
            else None,
            "median_ms": _median(i["one_pass"]["duration_ms"] for i in pairs),
            "contracts_passed": sum(1 for c in checks for k in CONTRACTS if c.get(k) == "ok"),
            "contracts_checked": len(checks) * len(CONTRACTS),
            "fact_recall": _mean(o.get("fact_recall") for _, o in judges),
            "truth_coverage": _mean(o.get("truth_coverage") for _, o in judges),
        },
        "agreement": {
            "fact_overlap": _mean((d.get("facts") or {}).get("overlap") for d in differences),
            "pointer_status": _mean(
                (d.get("pointers") or {}).get("agreement") for d in differences
            ),
            "pointer_score_gap": _mean(
                (d.get("pointers") or {}).get("mean_score_gap") for d in differences
            ),
            "dimension_status": _mean(
                (d.get("coaching") or {}).get("dimension_agreement") for d in differences
            ),
            "transcript_vocabulary": _mean(
                (d.get("transcript") or {}).get("vocabulary_overlap") for d in differences
            ),
        },
    }


def overview(connection: Any, *, limit: int = 200) -> dict[str, Any]:
    """Every compared call (newest first) and a summary each for real and fictional calls."""
    rows = _latest(connection)
    subjects: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.recording_id or row.bench_call)
        subjects.setdefault(key, {"recording_id": row.recording_id, "bench_call": row.bench_call})
    items: list[dict[str, Any]] = []
    for subject in list(subjects.values())[:limit]:
        result = call_compare(
            connection,
            recording_id=subject["recording_id"],
            bench_call=None if subject["recording_id"] else subject["bench_call"],
        )
        if result is not None:
            items.append(result)
    calls = [i for i in items if i["subject"]["kind"] == "call"]
    bench = [i for i in items if i["subject"]["kind"] == "bench"]
    return {
        "schema": SCHEMA,
        "summary": {"calls": summarise(calls), "bench": summarise(bench)},
        "items": [_line(i) for i in items],
    }


def _line(item: Mapping[str, Any]) -> dict[str, Any]:
    """One row of the list: numbers and ids only."""
    classic, one = item.get("classic") or {}, item.get("one_pass") or {}
    differences = item.get("differences") or {}
    checks = one.get("checks") or {}
    return {
        "subject": item["subject"],
        "audio_ms": one.get("audio_ms") or classic.get("audio_ms"),
        "classic": {
            "state": classic.get("state"),
            "cost_inr": classic.get("cost_inr"),
            "duration_ms": classic.get("duration_ms"),
        },
        "one_pass": {
            "state": one.get("state"),
            "reason": one.get("reason"),
            "cost_inr": one.get("cost_inr"),
            "flex_cost_inr": one.get("flex_cost_inr"),
            "duration_ms": one.get("duration_ms"),
            "contracts_ok": sum(1 for k in CONTRACTS if checks.get(k) == "ok"),
            "at": one.get("at"),
        },
        "fact_overlap": (differences.get("facts") or {}).get("overlap"),
        "pointer_agreement": (differences.get("pointers") or {}).get("agreement"),
        "dimension_agreement": (differences.get("coaching") or {}).get("dimension_agreement"),
    }


def money(value: Decimal | float | None) -> float | None:
    return None if value is None else round(float(value), 2)

"""The fictional benchmark set (cost research, 20 Oct 2026) through the one-pass pipeline.

Fictional calls only, never a real one: 16 scripted sales calls (English, Hindi,
Marathi, mixed), spoken by synthetic voices and sent through a phone codec. Their
audio is the research's 32 kbps MP3 (the shape Flash-Lite was measured on). While the
bench project's own Gemini key is refused, requests go to Google AI Studio through
OpenRouter on the research's account, with data collection denied; every request is
also written to the research ledger, whose budget guard counts it.

The classic side of each call is the research's own run of today's pipeline (the
product's prompt builders, Gemini 3.8 Flash) on the script itself, a perfect
transcript, so it is the best classic can do; its transcription cost is Scribe's list
price for that length (no Scribe run on fictional calls). The judges' scores (fact
recall against the script's fact sheet, coaching truth coverage) come along when the
research has them.

Folder: ``<root>/bench/audio/<id>/phone_8k.mp3`` and ``render.json``,
``<root>/bench/calls/<id>/script.json``, ``<root>/results/text/today/...``,
``<root>/results/ledger.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select

from ac_platform.call_data import extraction, taxonomy
from ac_platform.conversation_intelligence import pointer_review, reports
from ac_platform.one_pass import settings as choices
from ac_platform.one_pass import store
from ac_platform.one_pass.models import OnePassRun

CALL_DATE: Final = "Tuesday 20 October 2026"
CLASSIC_RUN: Final = Path("results/text/today/google_gemini-3.8-flash/oracle/run1")
CLASSIC_PREFIX: Final = "today:oracle:r1:"
SCRIBE_USD_PER_HOUR: Final = Decimal("0.22")
BUDGET_USD: Final = 2.0  # this pipeline's share of the research's OpenRouter credit
TAG: Final = "devlive:onepass:"
JUDGE: Final = "anthropic_claude-haiku-5.5"
STAGES: Final[dict[str, tuple[str, str]]] = {
    "C4": ("facts", "C4 facts"),
    "C5": ("coaching", "C5 report and coaching"),
    "pointer_review": ("pointer_review", "Pointer review"),
    "fast": ("fast", "Call data: fast"),
    "deep_extract": ("deep", "Call data: deep"),
    "deep_labels": ("deep", "Call data: deep"),
}


def call_ids(root: Path) -> list[str]:
    calls = root / "bench" / "calls"
    return sorted(
        p.name
        for p in calls.iterdir()
        if p.name.startswith("fx-")
        and (p / "script.json").exists()
        and (root / "bench" / "audio" / p.name / "phone_8k.mp3").exists()
    )


def oracle_transcript(root: Path, call: str) -> dict[str, Any]:
    """The script as a C2-shaped transcript (the research's ``oracle_transcript``)."""
    script = json.loads((root / "bench" / "calls" / call / "script.json").read_text("utf-8"))
    timing_path = root / "bench" / "audio" / call / "segments.json"
    timing = (
        {s["turn_id"]: s for s in json.loads(timing_path.read_text("utf-8"))}
        if timing_path.exists()
        else {}
    )
    speakers: dict[str, str] = {}
    segments: list[dict[str, Any]] = []
    clock = 0
    for turn in script["turns"]:
        known = timing.get(turn["id"])
        length = int(len(turn["text"].split()) / 2.4 * 1000) + 300
        start, end = (known["start_ms"], known["end_ms"]) if known else (clock, clock + length)
        start = max(int(start), 0)
        end = max(int(end), start + 1)
        speaker = speakers.setdefault(str(turn["speaker"]), f"speaker_{len(speakers)}")
        segments.append(
            {
                "id": f"s{len(segments) + 1}",
                "speaker_id": speaker,
                "start_ms": start,
                "end_ms": end,
                "text": str(turn["text"]).strip() or "-",
            }
        )
        clock = end + 300
    return {
        "source_sha256": hashlib.sha256(f"{call}:oracle".encode()).hexdigest(),
        "revision": "bench-oracle",
        "timebase_id": "bench",
        "duration_ms": max(int(s["end_ms"]) for s in segments),
        "segments": segments,
    }


def _ledger(root: Path) -> list[dict[str, Any]]:
    path = root / "results" / "ledger.jsonl"
    rows = []
    for line in path.read_text("utf-8").splitlines() if path.exists() else []:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def spent_usd(root: Path) -> float:
    return sum(
        float(r.get("billed_usd") or 0)
        for r in _ledger(root)
        if str(r.get("tag", "")).startswith(TAG)
    )


def _judge(folder: Path, call: str) -> dict[str, Any]:
    """Fact recall (share of the fact sheet stated with the right value) and coaching truth
    coverage, from the research's judges when present."""
    result: dict[str, Any] = {}
    facts = folder / "judge" / JUDGE / f"{call}.json"
    if facts.exists():
        data = json.loads(facts.read_text("utf-8"))
        truth = data.get("ground_truth") or []
        if truth:
            correct = sum(1 for t in truth if t.get("verdict") == "correct")
            result["fact_recall"] = round(correct / len(truth), 4)
            unsupported = sum(
                1 for s in data.get("system") or [] if s.get("verdict") == "unsupported"
            )
            result["unsupported_facts"] = unsupported
    report = folder / "rjudge" / JUDGE / f"{call}.json"
    if report.exists():
        data = json.loads(report.read_text("utf-8"))
        truths = data.get("truths") or []
        total = data.get("n_truths", len(truths))
        if isinstance(total, int) and total > 0:
            # The research's own count: covered is 1, partly covered a half.
            covered = sum(1 for t in truths if t.get("verdict") == "covered")
            partly = sum(1 for t in truths if "partial" in str(t.get("verdict")))
            result["truth_coverage"] = round((covered + 0.5 * partly) / total, 4)
            result["false_claims"] = len(data.get("false_claims") or [])
    return result


def classic_outcome(root: Path, call: str) -> store.Outcome | None:
    """The research's classic run of one fictional call, in this table's terms."""
    folder = root / CLASSIC_RUN
    path = folder / f"{call}.json"
    if not path.exists():
        return None
    result = json.loads(path.read_text("utf-8"))
    transcript = oracle_transcript(root, call)
    segments = extraction.segments_from_transcript(transcript)
    outputs: dict[str, Any] = {"c4_observation_count": len(result.get("c4_observations") or [])}
    checks: dict[str, Any] = {}
    drafts = []
    for part in ("fast", "deep"):
        if isinstance(result.get(part), dict):
            types = taxonomy.FAST_TYPES if part == "fast" else taxonomy.DEEP_EXTRACT_TYPES
            found, _ = extraction.validate_response(result[part], segments, types=types)
            drafts += [(part, d) for d in found]
    outputs["call_objects"] = [
        {
            "type_key": d.type_key,
            "display": d.display,
            "confidence": d.confidence,
            "basis": d.basis,
            "pipeline": part,
        }
        for part, d in drafts
    ]
    if isinstance(result.get("pointer_review"), dict):
        try:
            outputs["pointer_review"] = pointer_review.parse_review(
                result["pointer_review"], transcript["segments"]
            )
        except pointer_review.PointerReviewError as error:
            checks["pointer_review"] = str(error)
    if isinstance(result.get("c5"), dict):
        try:
            outputs["c5"] = reports.parse_report_draft(
                result["c5"], transcript, coaching_prompt_revision="coaching-v3"
            ).model_dump(mode="json", by_alias=True)
        except reports.ReportError as error:
            checks["c5"] = str(error)
            outputs["c5"] = {
                k: result["c5"].get(k)
                for k in (
                    "summary",
                    "verdict",
                    "strengths",
                    "improvements",
                    "missed_opportunities",
                    "objection_analysis",
                    "closing_analysis",
                    "dimensions",
                )
            }
    outputs["judge"] = _judge(folder, call)
    audio_ms = transcript["duration_ms"]
    render = root / "bench" / "audio" / call / "render.json"
    if render.exists():
        audio_ms = round(float(json.loads(render.read_text("utf-8"))["seconds"]) * 1000)
    stages: dict[str, dict[str, Any]] = {}
    # The research re-ran some stages; its result file is the last run, so each request
    # (call and tag) counts once, the last time it ran.
    latest: dict[str, dict[str, Any]] = {}
    for row in _ledger(root):
        tag = str(row.get("tag", ""))
        if row.get("call") == call and tag.startswith(CLASSIC_PREFIX):
            latest[tag] = row
    for tag, row in latest.items():
        name = tag[len(CLASSIC_PREFIX) :].split(".")[0]
        key, label = STAGES.get(name, (name, name))
        stage = stages.setdefault(
            key, {"key": key, "label": label, "inr": 0.0, "tokens_in": 0, "tokens_out": 0, "ms": 0}
        )
        stage["inr"] += float(row.get("list_usd") or 0) * 100
        stage["tokens_in"] += int(row.get("in") or 0)
        stage["tokens_out"] += int(row.get("out") or 0)
        stage["ms"] += round(float(row.get("latency_s") or 0) * 1000)
        stage["model"] = str(row.get("model", "")).replace("google/", "")
    scribe = float(Decimal(audio_ms) / Decimal(3_600_000) * SCRIBE_USD_PER_HOUR * 100)
    usage = {
        "stages": [
            {
                "key": "transcription",
                "label": "Transcription (Scribe)",
                "inr": round(scribe, 4),
                "ms": None,
                "model": "scribe_v2",
                "note": "list price for this length; the script stands in for its transcript",
            },
            *({**s, "inr": round(s["inr"], 4)} for s in stages.values()),
        ]
    }
    llm_inr = Decimal(str(round(sum(s["inr"] for s in stages.values()), 4)))
    return store.Outcome(
        state="succeeded",
        reason=None,
        audio_ms=audio_ms,
        transcription_cost_inr=Decimal(str(round(scribe, 4))),
        analysis_cost_inr=llm_inr,
        analysis_input_tokens=sum(s["tokens_in"] for s in stages.values()),
        analysis_output_tokens=sum(s["tokens_out"] for s in stages.values()),
        analysis_ms=sum(s["ms"] for s in stages.values()),
        duration_ms=round(float(result.get("wall_s") or 0) * 1000) or None,
        usage=usage,
        checks=checks,
        transcript=transcript,
        outputs=outputs,
    )


class LedgeredTransport:
    """Writes each request to the research ledger (its OpenRouter budget counts it)."""

    def __init__(self, inner: Any, root: Path, call: str) -> None:
        self.inner, self.root, self.call = inner, root, call
        self.name = inner.name

    def generate(self, *, model: str, request: Any, tier: str) -> Any:
        if spent_usd(self.root) >= BUDGET_USD:
            from ac_platform.one_pass.gemini import OnePassFailure

            raise OnePassFailure("bench_budget_reached")
        clock = time.monotonic()
        stage = "transcription" if request.audio is not None else "analysis"
        status, reply, usage = 200, None, None
        try:
            reply = self.inner.generate(model=model, request=request, tier=tier)
            usage = reply.usage
            return reply
        except Exception as error:
            status = 0
            # A failed answer (cut short, unreadable) was still billed: count what it used.
            usage = getattr(error, "usage", None)
            raise error
        finally:
            from ac_platform.one_pass import pricing

            row = {
                "at": round(time.time(), 1),
                "provider": "openrouter",
                "model": f"google/{model}",
                "tag": f"{TAG}{stage}",
                "call": self.call,
                "status": status,
                "in": usage.prompt if usage else 0,
                "out": usage.billed_output if usage else 0,
                "cached": usage.cached if usage else 0,
                "list_usd": float(pricing.cost_usd(model, usage, tier="standard"))
                if usage
                else 0.0,
                "billed_usd": getattr(reply, "provider_cost_usd", None)
                or (float(pricing.cost_usd(model, usage, tier="standard")) if usage else 0.0),
                "latency_s": round(time.monotonic() - clock, 2),
                "error": None if status == 200 else "failed",
            }
            with (self.root / "results" / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(row) + "\n")


def run(
    sessions: Any,
    root: Path,
    *,
    calls: list[str] | None,
    apply: bool,
    classic_only: bool,
    created_by: str,
    transport: Any = None,
    classic_again: bool = False,
) -> Iterator[dict[str, Any]]:
    from ac_platform.one_pass.gemini import OnePassFailure, OpenRouterBench
    from ac_platform.one_pass.runner import read_call

    wanted = calls or call_ids(root)
    models = {"transcription": choices.TRANSCRIPTION_MODEL, "analysis": choices.ANALYSIS_MODEL}
    settings = {**choices.defaults(), "mode": "both"}
    inner = transport or OpenRouterBench()
    for call in wanted:
        line: dict[str, Any] = {"bench_call": call}
        with sessions() as session, session.begin():
            connection = session.connection()
            have = {
                (row.pipeline, row.state)
                for row in connection.execute(
                    select(OnePassRun.pipeline, OnePassRun.state).where(
                        OnePassRun.bench_call == call
                    )
                )
            }
            if classic_again or ("classic", "succeeded") not in have:
                classic = classic_outcome(root, call)
                if classic is None:
                    line["classic"] = "missing"
                elif apply:
                    store.insert_classic_bench(
                        connection,
                        call,
                        outcome=classic,
                        models={"transcription": "scribe_v2", "analysis": "gemini-3.8-flash"},
                        created_by=created_by,
                        now=datetime.now(UTC),
                    )
                    line["classic"] = "imported"
            if classic_only or ("one_pass", "succeeded") in have:
                line["one_pass"] = "done" if ("one_pass", "succeeded") in have else "not_asked"
                yield line
                continue
            if not apply:
                line["dry_run"] = True
                yield line
                continue
            subject = store.Subject("bench", bench_call=call)
            started = store.start_run(
                connection,
                subject,
                trigger="bench",
                mode="both",
                settings=settings,
                models=models,
                created_by=created_by,
                now=datetime.now(UTC),
            )
        audio_path = root / "bench" / "audio" / call / "phone_8k.mp3"
        audio = audio_path.read_bytes()
        render = json.loads((audio_path.parent / "render.json").read_text("utf-8"))
        outcome = store.Outcome()
        try:
            read_call(
                LedgeredTransport(inner, root, call),
                audio=audio,
                mime="audio/mpeg",
                source_sha256=hashlib.sha256(audio).hexdigest(),
                duration_ms=round(float(render["seconds"]) * 1000),
                call_date=CALL_DATE,
                settings=settings,
                outcome=outcome,
            )
        except OnePassFailure as failure:
            outcome.state, outcome.reason = "failed", failure.outcome
        with sessions() as session, session.begin():
            store.finish_run(
                session.connection(),
                subject,
                started,
                outcome,
                trigger="bench",
                mode="both",
                models=models,
                created_by=created_by,
                now=datetime.now(UTC),
            )
        line["one_pass"] = (
            outcome.state if outcome.reason is None else f"{outcome.state}:{outcome.reason}"
        )
        if outcome.checks:
            line["contracts_ok"] = sum(1 for v in outcome.checks.values() if v == "ok")
        line["inr"] = float(outcome.cost_inr) if outcome.cost_inr is not None else None
        line["ms"] = outcome.duration_ms
        yield line

#!/usr/bin/env python3
"""Round 8 (21 Oct): GPT-6 Luna through the product's own one-pass requests in the FULL production formats.

``op_analysis.py`` is a pinned copy of ``ac_platform.one_pass.analysis`` at workbench 8fced2da (the module changes
under active development): two requests per call, ``facts`` (call data, notes -> C4 packet, 27-pointer review)
and ``report`` (C5 coaching-v5), merged and mapped onto the existing contracts by ``map_outputs``. Luna requests
go to OpenAI's API directly (bench project, fictional calls only, store=false). Results are written in the shape
the judges read (c4_observations, c5, deep facts, pointer_review). Variants (facts request / report request):

  base        Luna / Luna, the product prompts as they are
  strong      base's facts / Luna with a report-depth instruction
  stronghigh  base's facts / Luna, report-depth instruction, reasoning effort high
  hybrid      base's facts / Gemini 3.8 Flash (Google AI Studio via OpenRouter)
  flex        Luna / Luna, both on OpenAI's Flex tier (half price, slower)

Ledger tags: ``fullf_<variant>`` for facts requests, ``fullr_<variant>`` for report requests.

  fullpass.py <variant> [fx-01 ...]
"""

from __future__ import annotations

import json
import sys
import time

from common import BudgetExceeded, parse_json_text
import op_analysis as analysis
import providers as pv
import run as R

CALL_DATE = "Tuesday 20 October 2026"  # as the one-pass bench sends it
T = "asr/openrouter_google_gemini-3.1-flash-lite/phone_8k"
TDIR = T.replace("/", "_")
MODEL = "gpt-6-luna"

REPORT_DEPTH = """

REPORT DEPTH: before writing the report, walk through the whole call in time order and note for yourself every
coaching moment worth telling the salesperson: what they did well and what they should change, each tied to its
segments. Then fill the report from those notes: use as many strengths, improvements and missed opportunities as
the schema allows when the call has them, each one concrete moment (what was said, when, why it mattered, and for
improvements the better move), most important first. Cover the whole call, the middle and the end as well as the
opening. Do not shorten the report to save space."""


def out_path(variant: str, cid: str):
    return R.RES / "text" / f"full_{variant}" / f"openai_{MODEL}" / TDIR / "run1" / f"{cid}.json"


def judge_shape(answer: dict, transcript: dict) -> dict:
    """The answer through the product's contracts, in the shape run.py's judges read."""
    outputs, checks = analysis.map_outputs(answer, transcript)
    c4 = outputs.get("c4") or {}
    observations = [o.get("statement") or o.get("fact") for o in c4.get("observations", []) if isinstance(o, dict)]
    return {"errors": [f"{k}: {v}" for k, v in checks.items() if v not in ("ok", "ok_without_overview")],
            "checks": checks, "c4_observations": [o for o in observations if o],
            "c5": outputs.get("c5") or answer.get("report"), "fast": {"facts": []},
            "deep": {"facts": [{"type": o.get("type_key"), "value": o.get("display")}
                               for o in outputs.get("call_objects", [])]},
            "pointer_review": outputs.get("pointer_review"), "roles": outputs.get("roles")}


def ask_luna(req, cid: str, tag: str, *, extra: str = "", effort: str | None = None,
             tier: str | None = None) -> tuple[dict, dict]:
    messages = [{"role": "system", "content": req.system + extra}, {"role": "user", "content": req.user}]
    text, usage, _ = pv.openai_chat(MODEL, messages, tag=tag, call_id=cid, schema=req.schema, max_tokens=48_000,
                                    reasoning_effort=effort, service_tier=tier)
    return parse_json_text(text or ""), {k: usage.get(k) for k in ("in", "out", "cached", "reasoning", "list_usd",
                                                                   "tier", "schema_mode", "finish")}


def ask_gemini(req, cid: str, tag: str) -> tuple[dict, dict]:
    messages = [{"role": "system", "content": req.system}, {"role": "user", "content": req.user}]
    text, usage, _ = pv.openrouter_chat("google/gemini-3.8-flash", messages, tag=tag, call_id=cid, schema=req.schema,
                                        max_tokens=req.max_output_tokens, reasoning={"effort": "low"})
    if usage.get("status") == 400:  # AI Studio refuses this schema as a constraint: JSON mode, schema as text
        messages[0]["content"] += "\n\nReturn ONE JSON object matching this JSON schema:\n" + json.dumps(req.schema)
        text, usage, _ = pv.openrouter_chat("google/gemini-3.8-flash", messages, tag=tag, call_id=cid,
                                            max_tokens=req.max_output_tokens, reasoning={"effort": "low"},
                                            json_mode=True)
    return parse_json_text(R.strip_fences(text) or ""), {k: usage.get(k) for k in ("in", "out", "billed_usd", "status")}


def main() -> int:
    variant = sys.argv[1]
    calls = sys.argv[2:] or R.call_ids(type("A", (), {"calls": None})())
    for cid in calls:
        out = out_path(variant, cid)
        if out.exists():
            continue
        transcript = R.load_transcript(cid, T)
        reqs = analysis.requests(transcript, call_date=CALL_DATE)
        t0 = time.time()
        usage = {}
        try:
            if variant in ("strong", "stronghigh", "hybrid"):
                base = out_path("base", cid)
                prev = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {}
                if "facts" not in prev.get("_answers", {}):
                    print(cid, variant, "waits for base facts", flush=True)
                    continue
                facts, usage["facts"] = prev["_answers"]["facts"], {"reused_from": "base"}
            else:  # both requests at once, as the product sends them
                from concurrent.futures import ThreadPoolExecutor

                tier = "flex" if variant == "flex" else None
                with ThreadPoolExecutor(2) as pool:
                    f_job = pool.submit(ask_luna, reqs["facts"], cid, f"fullf_{variant}:{TDIR}:r1", tier=tier)
                    r_job = pool.submit(ask_luna, reqs["report"], cid, f"fullr_{variant}:{TDIR}:r1", tier=tier)
                    (facts, usage["facts"]), (report, usage["report"]) = f_job.result(), r_job.result()
            if variant in ("base", "flex"):
                pass
            elif variant == "hybrid":
                report, usage["report"] = ask_gemini(reqs["report"], cid, f"fullr_{variant}:{TDIR}:r1")
            else:
                report, usage["report"] = ask_luna(
                    reqs["report"], cid, f"fullr_{variant}:{TDIR}:r1",
                    extra=REPORT_DEPTH if variant in ("strong", "stronghigh") else "",
                    effort="high" if variant == "stronghigh" else None, tier="flex" if variant == "flex" else None)
            answer = analysis.merge({"facts": facts, "report": report})
            result = judge_shape(answer, transcript)
            result["_answers"] = {"facts": facts, "report": report}
        except BudgetExceeded as exc:
            print("stopped:", exc, flush=True)
            return 1
        except Exception as exc:  # a malformed answer is a quality result, recorded
            result = {"errors": [f"{variant}: {type(exc).__name__}: {str(exc)[:160]}"]}
        result["usage"] = usage
        result["wall_s"] = round(time.time() - t0, 1)
        R._write(out, result)
        print(cid, variant, "checks", result.get("checks"), "errors", len(result.get("errors", [])), result["wall_s"],
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

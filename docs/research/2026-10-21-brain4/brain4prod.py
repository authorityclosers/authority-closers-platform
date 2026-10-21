#!/usr/bin/env python3
# ruff: noqa: E501 - prompt text kept exactly as it ran
"""The product's Brain 4.0 prompt on the 7 gold-v1 real calls (Brain 4.0 session, 21 Oct 2026).

Approval (orchestrator, within the owner's ₹300 for checking Brain 4.0 against the coaching
lead's data): GPT-6 Luna Flex on the dev app key (store:false, signed DPA) and Gemini 3.8
Flash Flex on the dev app key; **hard cap ₹10 in all**, logged; only the existing Flash-Lite
transcripts are sent. Flex only: a busy answer is recorded as a failure, never retried on
the standard tier, so the price never doubles.

The request is exactly the shadow read's: system ``brain4_shadow.system_prompt()``, user rows
``pointer_review.build_prompt(segments)``, schema ``brain4.response_schema()``, answer checked
by ``brain4.parse``. Each read is saved as ratings only (runs/<model>/<call>.r<k>.json).

  brain4prod.py luna <reads>      (OPENAI_API_KEY in the environment)
  brain4prod.py gemini <reads>    (GEMINI_API_KEY in the environment)
  brain4prod.py spent
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from ac_platform.conversation_intelligence import brain4, brain4_shadow, pointer_review

HERE = Path(__file__).resolve().parent
REAL = Path("/home/acdev/research/analysis-cost-20261020/realcalls")
TRANSCRIPTS = REAL / "asr/openrouter_google_gemini-3.1-flash-lite/phone"
CALLS = [f"rc-{n:02d}" for n in range(1, 8)]
LEDGER = HERE / "brain4prod-ledger.jsonl"
CAP_INR = 10.0
INR_PER_USD = 100.0
# USD per million tokens, Flex (half the standard list price).
PRICES = {
    "luna": {"in": 0.05, "cached": 0.005, "out": 0.25},
    "gemini": {"in": 0.375, "cached": 0.0375, "out": 1.875},
    "gemini_critic": {"in": 0.375, "cached": 0.0375, "out": 1.875},
}
OUT_GUESS = {"luna": 4_500, "gemini": 3_500, "gemini_critic": 4_000}
# The critic variant (orchestrator, 21 Oct: Gemini keeps the coach's praise but misses his
# criticisms): the same request with a find-what-went-wrong step before rating.
CRITIC = (
    "\n\nCRITIC STEP (do this before you rate): reread the call as a demanding sales coach whose"
    " job is to find what went wrong. For every dimension, list to yourself each moment the"
    " salesperson could have handled better: interrupting, rushing or leaving no pauses, missing a"
    " follow-up question or a thread the prospect opened, assuming instead of asking, pitching or"
    " listing features before the need is clear, explaining price or terms nobody asked about,"
    " offering to send details instead of agreeing a clear next step. Then rate with those misses in"
    " view: give 4 or 5 only when you found no meaningful miss in that dimension; a dimension with a"
    " meaningful miss is 3 or lower. Put the most important miss in coaching."
)


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["inr"] for line in LEDGER.read_text().splitlines() if line.strip())


def observed_out(model: str) -> int:
    rows = [json.loads(x) for x in LEDGER.read_text().splitlines()] if LEDGER.exists() else []
    outs = [r["out"] for r in rows if r["model"] == model and r.get("out")]
    return max(outs) if outs else OUT_GUESS[model]


def transcript(call: str) -> list[dict[str, Any]]:
    data = json.loads((TRANSCRIPTS / f"{call}.json").read_text(encoding="utf-8"))
    out, speakers, last = [], {}, 0
    for i, s in enumerate(data["segments"], 1):
        speaker = speakers.setdefault(str(s.get("speaker", "?")), f"speaker_{len(speakers)}")
        start = max(int(s.get("start_ms", last)), 0)
        end = max(int(s.get("end_ms", start + 1000)), start + 1)
        text = str(s.get("text", "")).strip()
        if text:
            out.append(
                {
                    "id": f"s{i}",
                    "speaker_id": speaker,
                    "start_ms": start,
                    "end_ms": end,
                    "text": text,
                }
            )
            last = end
    return out


def inr(model: str, tokens_in: int, cached: int, tokens_out: int) -> float:
    p = PRICES[model]
    usd = ((tokens_in - cached) * p["in"] + cached * p["cached"] + tokens_out * p["out"]) / 1e6
    return round(usd * INR_PER_USD, 4)


def ask_luna(system: str, user: str) -> tuple[Any, dict[str, int], str]:
    body = {
        "model": "gpt-6-luna",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": False, "schema": brain4.response_schema()},
        },
        "max_completion_tokens": 20_000,
        "store": False,
        "service_tier": "flex",
    }
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json=body,
        timeout=httpx.Timeout(900.0, connect=20.0),
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    u = data.get("usage") or {}
    usage = {
        "in": int(u.get("prompt_tokens") or 0),
        "cached": int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        "out": int(u.get("completion_tokens") or 0),
    }
    if r.status_code != 200:
        return None, usage, f"http_{r.status_code}"
    text = data["choices"][0]["message"].get("content") or ""
    return json.loads(text), usage, str(data.get("service_tier") or "")


def ask_gemini(system: str, user: str) -> tuple[Any, dict[str, int], str]:
    body = {**brain4_shadow.gemini_body(system, user), "service_tier": "flex"}
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{brain4_shadow.MODEL_ID}:generateContent",
        headers={
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
            "content-type": "application/json",
        },
        json=body,
        timeout=httpx.Timeout(900.0, connect=20.0),
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    u = data.get("usageMetadata") or {}
    usage = {
        "in": int(u.get("promptTokenCount") or 0),
        "cached": int(u.get("cachedContentTokenCount") or 0),
        "out": int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0),
    }
    if r.status_code != 200:
        return None, usage, f"http_{r.status_code}"
    return pointer_review.decode_gemini(data), usage, "flex"


def run(model: str, reads: int, calls: list[str] | None = None) -> None:
    system = brain4_shadow.system_prompt() + (CRITIC if model == "gemini_critic" else "")
    ask = ask_luna if model == "luna" else ask_gemini
    folder = HERE / "runs" / model
    folder.mkdir(parents=True, exist_ok=True)
    for k in range(1, reads + 1):
        for call in calls or CALLS:
            out = folder / f"{call}.r{k}.json"
            if out.exists():
                continue
            segments = transcript(call)
            _, user = pointer_review.build_prompt(segments, {})
            estimate = inr(model, (len(system) + len(user)) // 3, 0, observed_out(model))
            if spent() + estimate > CAP_INR:
                print(
                    json.dumps(
                        {
                            "stopped": "cap",
                            "spent_inr": round(spent(), 2),
                            "next_estimate_inr": estimate,
                        }
                    )
                )
                return
            started = time.time()
            try:
                raw, usage, tier = ask(system, user)
            except (httpx.HTTPError, KeyError, ValueError) as error:
                raw, usage, tier = None, {"in": 0, "cached": 0, "out": 0}, type(error).__name__
            cost = inr(model, usage["in"], usage["cached"], usage["out"])
            row: dict[str, Any] = {
                "model": model,
                "call": call,
                "read": k,
                **usage,
                "inr": cost,
                "tier": tier,
                "seconds": round(time.time() - started, 1),
            }
            try:
                review = brain4.parse(raw, segments) if raw is not None else None
            except brain4.Brain4Error as error:
                review, row["error"] = None, str(error)
            row["ok"] = review is not None
            with LEDGER.open("a") as ledger:
                ledger.write(json.dumps(row) + "\n")
            print(json.dumps(row), flush=True)
            if review is not None:
                out.write_text(
                    json.dumps(
                        {
                            "ratings": {d["id"]: d["rating"] for d in review["dimensions"]},
                            "applicability": {
                                d["id"]: d["applicability"] for d in review["dimensions"]
                            },
                            "ethics_gate": review["ethics_gate"],
                            "model": model,
                        }
                    )
                )


if __name__ == "__main__":
    if sys.argv[1] == "spent":
        print(round(spent(), 4))
    else:
        run(sys.argv[1], int(sys.argv[2]), sys.argv[3].split(",") if len(sys.argv) > 3 else None)

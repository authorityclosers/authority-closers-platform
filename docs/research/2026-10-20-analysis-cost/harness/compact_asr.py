#!/usr/bin/env python3
"""Round 9 (21 Oct): a compact transcript format for Gemini 3.1 Flash-Lite, to cut output tokens.

Today's transcription asks for JSON segments with speaker, start and end MM:SS and text: on dense real calls that is
~1,120 output tokens per audio minute, of which ~360 are format (18 segments a minute). Styles:

  json           today's prompt and schema (the baseline, re-run on the same key)
  compact        one plain line per turn: "<speaker letter> <start second> <words>", no JSON, no end time
  compact_roman  compact, with Hindi and Marathi written in Latin letters (as people type them)

Lines become the same C2 segments (end = next start), so everything downstream reads them unchanged. Gemini is
called directly (GEMINI key from Infisical: env var named by GEMINI_KEY_VAR, default GEMINI_API_KEY), never via
OpenRouter. Usage: compact_asr.py <style> <fictional|real> [ids...]
"""

from __future__ import annotations

import json
import os
import re
import sys

from common import LEDGER, ROOT, b64, http_json, ledger_append, parse_json_text
import shapes as sh

MODEL = "gemini-3.1-flash-lite"
PRICES = (0.25, 1.50, 0.50)  # USD per million: text input, output, audio input (standard tier)
HARD_STOP_USD = 0.28  # under the orchestrator's $0.30 total for this key
COMPACT = """Transcribe this recorded phone call verbatim, every word, from start to end.
Write ONE line per speaker turn, nothing else:  <speaker> <start> <words>
- speaker: A, B, C... consistently by voice (the first voice heard is A).
- start: whole seconds from the start of the call when the turn begins (for example 754).
- words: exactly what is said. Hindi and Marathi in Devanagari script; English words (including English words inside
  Hindi/Marathi sentences) in Latin script. Do not translate, correct, summarise or skip anything.
- Numbers: write amounts, dates and times as digits when spoken as numbers ("12.5 lakh", "27 October", "2:30").
- Split a turn longer than ~30 seconds into lines. If something is inaudible write [inaudible]; never guess words.
No JSON, no headings, no blank lines."""
COMPACT_ROMAN = COMPACT.replace(
    "Hindi and Marathi in Devanagari script; English words (including English words inside\n"
    "  Hindi/Marathi sentences) in Latin script.",
    "Write Hindi and Marathi in Latin letters, the way people type them in WhatsApp (for example \"aapka budget\n"
    "  kitna hai\"); English words as English.")
assert COMPACT_ROMAN != COMPACT
COMPACT2 = """Transcribe this recorded phone call verbatim, every word, from start to end.
Write ONE line per speaker turn, nothing else, in exactly this form:
[MM:SS] S1: words
- [MM:SS]: when the turn starts, minutes and seconds from the start of the call.
- S1, S2, S3...: the speaker, decided by the voice and kept consistent for the whole call (the first voice heard is
  S1). Start a new line with the other label every time the voice changes; sales calls mostly alternate between two
  voices.
- words: exactly what is said. Hindi and Marathi in Devanagari script; English words (including English words inside
  Hindi/Marathi sentences) in Latin script. Do not translate, correct, summarise or skip anything.
- Numbers: write amounts, dates and times as digits when spoken as numbers ("12.5 lakh", "27 October", "2:30").
- Split a turn longer than ~30 seconds into lines. If something is inaudible write [inaudible]; never guess words.
- Never repeat a line you have already written. No JSON, no headings, no blank lines."""
LINE2 = re.compile(r"^\s*\[(\d{1,3}):(\d{2})(?::(\d{2}))?\]\s*(S\d+|[A-Z])\s*:\s*(.+?)\s*$")
LINE = re.compile(r"^\s*([A-Z])\s*[:|]?\s+(\d{1,5})(?:s)?\s*[:|-]?\s+(.+?)\s*$")


def audio_path(kind: str, cid: str):
    if kind == "real":
        flac = ROOT / "realcalls" / "audio" / cid / "phone.flac"
    else:
        flac = ROOT / "bench" / "audio" / cid / "phone_8k.flac"
    mp3 = flac.with_suffix(".mp3")
    if not mp3.exists():
        import subprocess

        subprocess.run(["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error", "-i", str(flac), "-ac", "1",
                        "-b:a", "32k", str(mp3)], check=True)
    return mp3


def parse_compact(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        m2 = LINE2.match(line)
        if m2:
            a, b, c = int(m2.group(1)), int(m2.group(2)), m2.group(3)
            secs = a * 3600 + b * 60 + int(c) if c else a * 60 + b
            rows.append({"speaker": m2.group(4), "start_ms": secs * 1000, "text": m2.group(5)})
            continue
        m = LINE.match(line)
        if m:
            rows.append({"speaker": m.group(1), "start_ms": int(m.group(2)) * 1000, "text": m.group(3)})
    for i, r in enumerate(rows):
        nxt = rows[i + 1]["start_ms"] if i + 1 < len(rows) else r["start_ms"] + 5000
        r["end_ms"] = max(nxt, r["start_ms"] + 500)
    return rows


def main() -> int:
    style, kind = sys.argv[1], sys.argv[2]
    ids = sys.argv[3:] or (sorted(p.name for p in (ROOT / "realcalls" / "audio").iterdir()) if kind == "real" else
                           sorted(p.name for p in (ROOT / "bench" / "audio").iterdir() if p.name.startswith("fx-")))
    key = os.environ[os.environ.get("GEMINI_KEY_VAR", "GEMINI_API_KEY")]
    base = (ROOT / "realcalls") if kind == "real" else (ROOT / "results")
    for cid in ids:
        out = base / "asr" / f"gemini-direct_{MODEL}_{style}" / ("phone" if kind == "real" else "phone_8k") / f"{cid}.json"
        if out.exists():
            continue
        # hard stop (orchestrator, 21 Oct: $0.30 in total on the staging project's key), counted at standard prices
        spent = sum(float(json.loads(l).get("list_usd") or 0) for l in LEDGER.read_text(encoding="utf-8").splitlines()
                    if json.loads(l).get("provider") == "gemini-direct")
        if spent >= HARD_STOP_USD:
            print("hard stop: $%.3f spent on gemini-direct" % spent, flush=True)
            return 1
        prompt = {"json": sh.ASR_PROMPT, "compact": COMPACT, "compact_roman": COMPACT_ROMAN, "compact2": COMPACT2}[style]
        cfg = {"maxOutputTokens": 65_536, "temperature": 0, "thinkingConfig": {"thinkingLevel": "LOW"}}
        if style == "json":
            cfg.update({"responseMimeType": "application/json", "responseJsonSchema": sh.asr_schema()})
        body = {"contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "audio/mp3", "data": b64(audio_path(kind, cid))}}, {"text": prompt}]}],
            "generationConfig": cfg}
        tier = os.environ.get("GEMINI_TIER", "flex")
        if tier == "flex":
            body["serviceTier"] = "flex"
        status, resp, dt = http_json(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                                     body, {"x-goog-api-key": key}, timeout=1200)
        if status == 400 and tier == "flex":  # field refused: standard tier
            body.pop("serviceTier", None)
            tier = "standard"
            status, resp, dt = http_json(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                                         body, {"x-goog-api-key": key}, timeout=900)
        u = resp.get("usageMetadata", {}) if isinstance(resp, dict) else {}
        audio_in = sum(d.get("tokenCount", 0) for d in u.get("promptTokensDetails", []) if d.get("modality") == "AUDIO")
        tin, tout = int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
        usd = ((tin - audio_in) * PRICES[0] + audio_in * PRICES[2] + tout * PRICES[1]) / 1e6
        text = None
        try:
            text = "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"] if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            pass
        ledger_append({"provider": "gemini-direct", "model": f"google/{MODEL}", "tag": f"asr9:{style}:{kind}",
                       "call": cid, "status": status, "tier": tier, "in": tin, "audio_in": audio_in, "out": tout,
                       "thoughts": u.get("thoughtsTokenCount", 0), "list_usd": round(usd, 6),
                       "billed_usd": round(usd * (0.5 if tier == "flex" else 1.0), 6),
                       "latency_s": round(dt, 2), "error": None if status == 200 else str(resp)[:300]})
        if style == "json":
            try:
                segs = [{"speaker": s["speaker"], "start_ms": int(sum(float(x) * 60 ** i for i, x in enumerate(reversed(str(s["start"]).split(":")))) * 1000),
                         "end_ms": int(sum(float(x) * 60 ** i for i, x in enumerate(reversed(str(s["end"]).split(":")))) * 1000),
                         "text": s["text"]} for s in parse_json_text(text or "")["segments"]]
            except Exception:
                segs = []
        else:
            segs = parse_compact(text or "")
        res = {"status": status, "segments": segs, "usage": {"in": tin, "audio_in": audio_in, "out": tout, "usd": usd}}
        out.parent.mkdir(parents=True, exist_ok=True)
        (out if segs else out.with_suffix(".failed")).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print(cid, style, status, len(segs), "segments", tout, "out tokens", round(dt, 1), "s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Round 3 (owner-approved 21 Oct 2026): real calls annotated by the coaching lead. Research only.

Gemini 3.1 Flash-Lite transcribes the audio; today's six stages and one pass (Gemini 3.8 Flash, GPT-6 Luna) analyse
the same transcripts; Gemini 3.8 Flash and GPT-6 Luna judge every report against the lead's notes. Only Google AI
Studio and OpenAI see the data (BENCH_STRICT=1: zero data retention, no fallback hosts). Data lives under
$BENCH_ROOT/realcalls/ and never goes into git: raw/, audio/, asr/, text/, rjudge/, map.json, truths.json.

  realcalls.py prep | asr | text | judge | score
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict

from common import LEDGER, ROOT, parse_json_text
import run as R

RC = ROOT / "realcalls"
ASR_ARM = "openrouter:google/gemini-3.1-flash-lite"
VARIANT = "phone"
TRANSCRIPT = "asr/openrouter_google_gemini-3.1-flash-lite/phone"
ARMS = [("today", "google/gemini-3.8-flash"), ("onepass2", "google/gemini-3.8-flash"),
        ("onepass", "openai/gpt-6-luna"), ("onepass3", "openai/gpt-6-luna")]
JUDGES = ["google/gemini-3.8-flash", "openai/gpt-6-luna", "anthropic/claude-haiku-5.5"]
# round 4: one pass on the coaching lead's Brain 4.0 rubric, cheap to premium models (owner, 21 Oct: any provider)
ARMS4 = [("brain4", "openai/gpt-6-luna"), ("brain4", "openai/gpt-6-luna-pro"), ("brain4", "google/gemini-3.8-flash"),
         ("brain4", "anthropic/claude-sonnet-5.5"), ("brain4", "openai/gpt-6.1-sol")]
ARMS5 = [("brain4d", "openai/gpt-6-luna")]
ARMS6 = [("brain4m", "openai/gpt-6-luna")]
ARMS7 = [("brain4n", "openai/gpt-6-luna"), ("brain4n", "anthropic/claude-sonnet-5.5"), ("brain4n", "google/gemini-3.8-flash")]
ALL_ARMS = ARMS + ARMS4 + ARMS5 + ARMS6 + ARMS7
if os.environ.get("RC_ROUND") == "4":
    ARMS = ARMS4
elif os.environ.get("RC_ROUND") == "5":
    ARMS = ARMS5
elif os.environ.get("RC_ROUND") == "6":
    ARMS = ARMS6
elif os.environ.get("RC_ROUND") == "7":
    ARMS = ARMS7
if os.environ.get("RC_PROVIDERS"):  # e.g. "google" while the OpenAI route waits for the owner
    _keep = tuple(f"{x}/" for x in os.environ["RC_PROVIDERS"].split(","))
    ARMS = [a for a in ARMS if a[1].startswith(_keep)]
    JUDGES = [j for j in JUDGES if j.startswith(_keep)]
FX = 100.0

# the product's harness code, pointed at the real-call folder
R.RES = RC
R.AUDIO = RC / "audio"

RJUDGE_REAL = """You are a strict judge of sales-coaching reports. You get the notes an expert sales coach wrote while
listening to a real recorded call (each note has a kind: strength, improvement or observation; an optional MM:SS
time; and the point), the system's coaching output (report and pointer notes), and an automatic transcript of the
call that may contain recognition errors. For each expert note decide whether the system's output identifies the same
point: "covered" (same behaviour or moment with the same judgement; a strength the system calls a weakness is not
covered), "partial" (related but vague, incomplete, or placed at another moment) or "not_covered". Then list the
system's coaching claims that the transcript contradicts or that rest on things that never happened ("false_claims",
one short sentence each), and the system's claims that directly contradict an expert note ("contradictions", each
naming the note id). Do not count style or wording differences. Return JSON only."""


def rjudge_real_schema() -> dict:
    s = R.rjudge_schema()
    s["properties"]["contradictions"] = {"type": "array", "items": {"type": "string"}}
    s["required"] = list(s.get("required", [])) + ["contradictions"]
    return s


def ids() -> list[str]:
    return sorted(p.name for p in (RC / "audio").iterdir() if (p / f"{VARIANT}.flac").exists())


def truths() -> dict:
    return {k: v for k, v in json.loads((RC / "truths.json").read_text(encoding="utf-8")).items() if k.startswith("rc-")}


def cmd_prep() -> None:
    mapping = json.loads((RC / "map.json").read_text(encoding="utf-8"))
    durations = {}
    for cid, raw in sorted(mapping.items()):
        out = RC / "audio" / cid / f"{VARIANT}.flac"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            subprocess.run(["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error", "-i", str(RC / "raw" / raw),
                            "-ac", "1", "-ar", "16000", str(out)], check=True)
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True, check=True)
        durations[cid] = round(float(p.stdout.strip()) / 60, 2)
        print(cid, durations[cid], "min", flush=True)
    (RC / "durations.json").write_text(json.dumps(durations, indent=1), encoding="utf-8")


def cmd_asr() -> None:
    R.cmd_asr(argparse.Namespace(arm=ASR_ARM, variant=VARIANT, calls=ids(), force=False))


def cmd_text() -> None:
    for shape, model in ARMS:
        R.cmd_text(argparse.Namespace(shape=shape, model=model, transcript=TRANSCRIPT, run=1, calls=ids(), force=False))


def result_dir(shape: str, model: str):
    return RC / "text" / shape / model.replace("/", "_") / TRANSCRIPT.replace("/", "_") / "run1"


def cmd_judge() -> None:
    gold = truths()
    judges = [j for j in JUDGES if not os.environ.get("RC_JUDGES") or j in os.environ["RC_JUDGES"].split(",")]
    for shape, model in ARMS:
        for judge in judges:
            for cid in ids():
                notes = gold.get(cid) or []
                path = result_dir(shape, model) / f"{cid}.json"
                out = result_dir(shape, model) / "rjudge" / judge.replace("/", "_") / f"{cid}.json"
                if not notes or not path.exists() or out.exists():
                    continue
                coaching = R.system_coaching(json.loads(path.read_text(encoding="utf-8")))
                if not coaching.get("report"):
                    R._write(out, {"error": "no report", "n_truths": len(notes)})
                    continue
                transcript = R.load_transcript(cid, TRANSCRIPT)
                user = ("Expert coach's notes:\n" + json.dumps(notes, ensure_ascii=False) + "\n\nSystem coaching output:\n"
                        + json.dumps(coaching, ensure_ascii=False)[:60000] + "\n\nTranscript (MM:SS from start):\n"
                        + "\n".join(f"[{s['start_ms'] // 60000}:{s['start_ms'] // 1000 % 60:02d}] {s['speaker_id']}: {s['text']}"
                                    for s in transcript["segments"]))
                body = {"systemInstruction": {"parts": [{"text": RJUDGE_REAL}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {"responseMimeType": "application/json",
                                             "responseJsonSchema": rjudge_real_schema(), "maxOutputTokens": 8_000,
                                             "temperature": 0, "thinkingConfig": {"thinkingLevel": "LOW"}}}
                text, _ = R.make_send(judge, cid, f"rc-judge:{shape}:{model}")(body, "rjudge")
                try:
                    verdict = parse_json_text(text or "")
                except Exception as exc:
                    verdict = {"error": type(exc).__name__}
                verdict["n_truths"] = len(notes)
                R._write(out, verdict)
                print(cid, shape, model, "judged by", judge, flush=True)


def cmd_score() -> None:
    gold = truths()
    mins = json.loads((RC / "durations.json").read_text(encoding="utf-8"))
    spend: dict[tuple, float] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("status") == 200 and str(r.get("call", "")).startswith("rc-"):
            spend[(r["model"], r.get("tag"), r["call"])] = float(r.get("billed_usd") or r.get("list_usd") or 0)
    rows = []
    judges_all = ["google/gemini-3.8-flash", "openai/gpt-6-luna", "anthropic/claude-haiku-5.5", "claude-sub/sonnet"]
    for shape, model in ALL_ARMS:
        usd = sum(v for (m, tag, _), v in spend.items() if m == model and str(tag).startswith(f"{shape}:"))
        asr_usd = sum(v for (m, tag, _), v in spend.items() if str(tag).startswith("asr:"))
        total_min = sum(mins.values())
        for judge in judges_all:
            n = cov = 0.0
            by_kind: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
            false_claims = contradictions = calls = 0
            per_call = {}
            for cid in ids():
                f = result_dir(shape, model) / "rjudge" / judge.replace("/", "_") / f"{cid}.json"
                if not f.exists() or not gold.get(cid):
                    continue
                v = json.loads(f.read_text(encoding="utf-8"))
                kinds = {t["id"]: t["kind"] for t in gold[cid]}
                verdicts = {t.get("id"): t.get("verdict") for t in v.get("truths", [])} if "error" not in v else {}
                c_cov = 0.0
                for tid, kind in kinds.items():
                    score = {"covered": 1.0, "partial": 0.5}.get(verdicts.get(tid), 0.0)
                    by_kind[kind][0] += score
                    by_kind[kind][1] += 1
                    c_cov += score
                n += len(kinds)
                cov += c_cov
                calls += 1
                false_claims += len(v.get("false_claims", []) or [])
                contradictions += len(v.get("contradictions", []) or [])
                per_call[cid] = round(c_cov / len(kinds), 3)
            if not calls:
                continue
            rows.append({"arm": f"{shape}:{model}", "judge": judge, "calls": calls, "notes": int(n),
                         "coverage": round(cov / n, 4) if n else None,
                         "by_kind": {k: round(a / b, 4) for k, (a, b) in by_kind.items() if b},
                         "false_claims_per_call": round(false_claims / calls, 2) if calls else None,
                         "contradictions_per_call": round(contradictions / calls, 2) if calls else None,
                         "per_call": per_call,
                         "analysis_inr_per_min": round(usd * FX / total_min, 4) if total_min else None,
                         "asr_inr_per_min": round(asr_usd * FX / total_min, 4) if total_min else None})
    (RC / "scores.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("| arm | judge | calls | notes | coverage | strengths | improvements | observations | false claims/call | contradictions/call | ₹/min analysis |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"
    for r in rows:
        k = r["by_kind"]
        print(f"| {r['arm']} | {r['judge']} | {r['calls']} | {r['notes']} | {pct(r['coverage'])} | {pct(k.get('strength'))} | "
              f"{pct(k.get('improvement'))} | {pct(k.get('observation'))} | {r['false_claims_per_call']} | "
              f"{r['contradictions_per_call']} | {r['analysis_inr_per_min']} |")


# ---------------------------------------------------------------- round 5: delivery observations from the audio
DELIVERY_PROMPT = """Listen to this recorded sales phone call. Do not transcribe it. Report how the speakers SOUND,
especially the salesperson, as observations a coach can check by listening at the given time:
- pace: rushed, steady or slow, and where it changes (for example speeding up after a price question or objection);
- pauses: pauses after important questions, after the price, after objections and after a closing question, or
  their absence (answers given instantly, every silence filled, stacked questions without waiting);
- interruptions: talking over the other speaker, cutting answers short (natural short overlaps like "haan" are fine);
- tone: warm, flat, nervous, apologetic, confident, scripted or read-out, and whether it changes at price, objections
  or the close; whether the two speakers' energy matches.
Give 8-20 observations in time order, each with MM:SS, speaker (salesperson or prospect), category (pace, pause,
interruption, tone), what you hear, and whether it helps or hurts the call. Then one overall line each for the
salesperson's pace, use of pauses and tone. Only what you can hear; do not judge what is said."""


def delivery_schema() -> dict:
    s = {"type": "string"}
    return {"type": "object", "properties": {
        "observations": {"type": "array", "items": {"type": "object", "properties": {
            "time": s, "speaker": s, "category": {"type": "string", "enum": ["pace", "pause", "interruption", "tone"]},
            "observation": s, "effect": {"type": "string", "enum": ["helps", "hurts", "neutral"]}},
            "required": ["time", "speaker", "category", "observation", "effect"]}},
        "overall_pace": s, "overall_pauses": s, "overall_tone": s},
        "required": ["observations", "overall_pace", "overall_pauses", "overall_tone"]}


def cmd_delivery() -> None:
    for cid in ids():
        out = RC / "delivery" / f"{cid}.json"
        if out.exists():
            continue
        text, usage, _ = R.openrouter_audio("google/gemini-3.1-flash-lite", RC / "audio" / cid / f"{VARIANT}.flac",
                                            DELIVERY_PROMPT, delivery_schema(), cid, "delivery:phone")
        try:
            R._write(out, {**parse_json_text(text or ""), "usage": usage})
        except Exception as exc:
            R._write(out.with_suffix(".failed"), {"error": type(exc).__name__, "raw_head": (text or "")[:300]})
        print(cid, "delivery", usage.get("status"), flush=True)


def cmd_brain4d() -> None:
    """Brain 4.0 one pass that also reads the audio delivery observations (shape brain4d)."""
    import shapes as sh
    models = os.environ.get("RC_MODELS", "openai/gpt-6-luna").split(",")
    system = sh.BRAIN4_SYSTEM + """

DELIVERY OBSERVATIONS: after the transcript you also get observations of how the speakers sound, taken from the
audio by a listening model (times are MM:SS). Use them as audio evidence for D03 Tone, Pace & Pauses (score it from
them, with medium confidence at most) and, where relevant, for D01, D04, D06 and D15; cite them as "audio MM:SS"."""
    brain4_with(models, "brain4d", "delivery", system, "Delivery observations from the audio:")


MEASURED_NOTE = """

MEASURED DELIVERY: after the transcript you also get pause statistics measured from the call audio (both speakers
mixed): silence share, pauses per minute, the longest stretch of talk without a pause, and the same per 2-minute
window. They are measurements, not judgements. Lively but unhurried sales calls usually have pauses of 0.5 s or more
around 8-14 times a minute; far fewer pauses, a low silence share or very long stretches without a pause mean the
conversation is rushed and leaves the buyer no time to think. Use them as audio evidence for D03 Tone, Pace & Pauses
(medium confidence at most, since they do not separate the speakers) and, where relevant, D04 and D14; cite them as
"measured"."""


def cmd_brain4m() -> None:
    """Brain 4.0 one pass that also reads measured pause statistics (shape brain4m)."""
    import shapes as sh
    models = os.environ.get("RC_MODELS", "openai/gpt-6-luna").split(",")
    if os.environ.get("RC_NOTES") == "1":  # round 7: plus the coach's timestamped moment notes
        brain4_with(models, "brain4n", "measured", sh.BRAIN4_SYSTEM + MEASURED_NOTE + sh.COACH_NOTES_INSTRUCTION,
                    "Measured pause statistics from the audio:", notes=True)
        return
    brain4_with(models, "brain4m", "measured", sh.BRAIN4_SYSTEM + MEASURED_NOTE, "Measured pause statistics from the audio:")


def brain4_with(models: list[str], shape: str, folder: str, system: str, label: str, notes: bool = False) -> None:
    import shapes as sh
    for model in models:
        for cid in ids():
            out = result_dir(shape, model) / f"{cid}.json"
            dfile = RC / folder / f"{cid}.json"
            if out.exists() or not dfile.exists():
                continue
            transcript = R.load_transcript(cid, TRANSCRIPT)
            d = json.loads(dfile.read_text(encoding="utf-8"))
            d.pop("usage", None)
            _, user = sh.onepass_messages(transcript["segments"], R.CALL_DATE)
            user += "\n\n" + label + "\n" + json.dumps(d, ensure_ascii=False)
            schema = sh.brain4_schema(notes)
            sys_text, cfg = system, {"responseMimeType": "application/json", "responseJsonSchema": schema,
                                     "maxOutputTokens": 28_000, "thinkingConfig": {"thinkingLevel": "LOW"}}
            if notes and not model.startswith("openai/"):
                # Anthropic ("compiled grammar is too large") and Google (400) refuse this schema as a constraint:
                # plain JSON mode with the schema written into the prompt
                cfg.pop("responseJsonSchema")
                sys_text = system + "\n\nReturn ONE JSON object only, matching this JSON schema:\n" + json.dumps(schema)
            body = {"systemInstruction": {"parts": [{"text": sys_text}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": cfg}
            text, _ = R.make_send(model, cid, f"{shape}:{TRANSCRIPT.replace('/', '_')}:r1")(body, "onepass")
            try:
                result = {"onepass": parse_json_text(text or ""), "errors": []}
            except Exception as exc:
                result = {"errors": [f"onepass: {type(exc).__name__}"], "raw_head": (text or "")[:300]}
            R._write(out, result)
            print(cid, shape, model, "errors:", len(result["errors"]), flush=True)


# ---------------------------------------------------------------- round 6: measured delivery features (local, free)
def measure(cid: str) -> dict:
    """Silences from ffmpeg silencedetect (-30 dB, >= 0.5 s) -> pause statistics overall and per 2-minute window."""
    import re
    audio = RC / "audio" / cid / f"{VARIANT}.flac"
    p = subprocess.run(["nice", "-n", "19", "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio), "-af",
                        "silencedetect=noise=-30dB:d=0.5", "-f", "null", "-"], capture_output=True, text=True)
    ends = [(float(a), float(b)) for a, b in re.findall(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", p.stderr)]
    dur = json.loads((RC / "durations.json").read_text(encoding="utf-8"))[cid] * 60
    sil = [(e - d, e, d) for e, d in ends]
    talk, last = [], 0.0  # stretches of continuous sound between pauses
    for st, en, _ in sil:
        talk.append((st - last, last))
        last = en
    talk.append((dur - last, last))
    windows = []
    for w0 in range(0, int(dur), 120):
        ws = [d for st, _, d in sil if w0 <= st < w0 + 120]
        span = min(120, dur - w0) / 60
        windows.append({"from": f"{w0 // 60:02d}:{w0 % 60:02d}", "pauses_per_min": round(len(ws) / span, 1),
                        "silence_share": round(sum(ws) / (span * 60), 3)})
    longest, t0 = max(talk)
    return {"minutes": round(dur / 60, 1), "silence_share": round(sum(d for *_, d in sil) / dur, 3),
            "pauses_ge_0_5s_per_min": round(len(sil) / (dur / 60), 1),
            "pauses_ge_1s_per_min": round(sum(1 for *_, d in sil if d >= 1.0) / (dur / 60), 1),
            "longest_talk_without_pause_s": round(longest, 1),
            "longest_talk_starts_at": f"{int(t0) // 60:02d}:{int(t0) % 60:02d}", "by_2_min": windows,
            "note": "Measured on the mixed phone audio (both speakers): a pause is >= 0.5 s below -30 dB."}


def cmd_measure() -> None:
    for cid in ids():
        out = RC / "measured" / f"{cid}.json"
        if not out.exists():
            R._write(out, measure(cid))
            print(cid, "measured", flush=True)


if __name__ == "__main__":
    # 21 Oct, owner: retention and training do not matter for these calls; BENCH_STRICT=1 (Vertex/Azure zero
    # retention) was used for the first Google and Luna runs and is optional from round 4 on.
    {"prep": cmd_prep, "asr": cmd_asr, "text": cmd_text, "judge": cmd_judge, "score": cmd_score,
     "delivery": cmd_delivery, "brain4d": cmd_brain4d, "measure": cmd_measure, "brain4m": cmd_brain4m}[sys.argv[1]]()

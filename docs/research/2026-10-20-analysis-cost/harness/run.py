#!/usr/bin/env python3
"""Benchmark driver (analysis-cost research, fictional calls only). API calls only; run under nice/ionice.

  run.py asr   --arm gemini:gemini-2.5-flash-lite|groq:whisper-large-v3-turbo|deepgram:nova-3|assemblyai:universal-2|
                     elevenlabs:scribe_v2   --variant phone_8k|clean_16k  [--calls fx-01 ...]
  run.py text  --shape today|onepass --model gemini-3.8-flash|anthropic/claude-haiku-5.5|...
               --transcript oracle|asr/<arm>/<variant>  [--run 1]
  run.py audio1 --model gemini-2.5-flash-lite --variant phone_8k          (shape c: audio -> transcript + analysis)
  run.py judge --result <results/text/...dir> --judge gemini-3.8-flash|anthropic/claude-haiku-5.5

Outputs under $BENCH_ROOT/results/. Every request is in results/ledger.jsonl.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from common import ROOT, BudgetExceeded, b64, parse_json_text
import providers as pv
import shapes as sh

CALLS = ROOT / "bench" / "calls"
AUDIO = ROOT / "bench" / "audio"
RES = ROOT / "results"
CALL_DATE = "2026-10-20"


def call_ids(args) -> list[str]:
    if args.calls:
        return args.calls
    return [p.name for p in sorted(CALLS.iterdir()) if (p / "facts.json").exists() and not p.name.startswith("sm-")]


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _ms(clock: str) -> int:
    parts = [float(x) for x in re.findall(r"[\d.]+", str(clock))] or [0.0]
    secs = 0.0
    for p in parts[-3:]:
        secs = secs * 60 + p
    return int(secs * 1000)


def c2_transcript(call_id: str, segments: list[dict], tag: str) -> dict:
    """Product-shaped (C2 checkpoint) transcript from any segment list."""
    out, speakers, last = [], {}, 0
    for i, s in enumerate(segments, 1):
        spk = speakers.setdefault(str(s.get("speaker", "?")), f"speaker_{len(speakers)}")
        st = max(int(s.get("start_ms", last)), 0)
        en = max(int(s.get("end_ms", st + 1000)), st + 1)
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        out.append({"id": f"s{i}", "speaker_id": spk, "start_ms": st, "end_ms": en, "text": text})
        last = en
    return {"source_sha256": hashlib.sha256(f"{call_id}:{tag}".encode()).hexdigest(), "revision": f"bench-{tag}",
            "timebase_id": "bench", "duration_ms": max(s["end_ms"] for s in out), "segments": out}


def oracle_transcript(call_id: str) -> dict:
    script = json.loads((CALLS / call_id / "script.json").read_text(encoding="utf-8"))
    seg_path = AUDIO / call_id / "segments.json"
    timing = {s["turn_id"]: s for s in json.loads(seg_path.read_text())} if seg_path.exists() else {}
    segs, t = [], 0
    for turn in script["turns"]:
        tm = timing.get(turn["id"])
        dur = int(len(turn["text"].split()) / 2.4 * 1000) + 300
        st, en = (tm["start_ms"], tm["end_ms"]) if tm else (t, t + dur)
        segs.append({"speaker": turn["speaker"], "start_ms": st, "end_ms": en, "text": turn["text"]})
        t = en + 300
    return c2_transcript(call_id, segs, "oracle")


def load_transcript(call_id: str, which: str) -> dict:
    if which == "oracle":
        return oracle_transcript(call_id)
    data = json.loads((RES / which / f"{call_id}.json").read_text(encoding="utf-8"))
    return c2_transcript(call_id, data["segments"], which.replace("/", "_"))


# ------------------------------------------------------------------ senders
def make_send(model: str, call_id: str, tag_prefix: str):
    def send(body: dict, tag: str):
        if model.startswith("gemini"):
            body = json.loads(json.dumps(body))
            cfg = body.setdefault("generationConfig", {})
            if model.startswith("gemini-2.5"):
                cfg["thinkingConfig"] = {"thinkingBudget": 0}
            text, usage, _ = pv.gemini_generate(model, body, tag=f"{tag_prefix}:{tag}", call_id=call_id)
            return text, usage
        from today import to_messages

        msgs, schema, max_out = to_messages(body)
        cfg = body.get("generationConfig", {})
        text, usage, _ = pv.openrouter_chat(model, msgs, tag=f"{tag_prefix}:{tag}", call_id=call_id, schema=schema,
                                            max_tokens=max_out, temperature=cfg.get("temperature"),
                                            reasoning=reasoning_for(model),
                                            json_mode=cfg.get("responseMimeType") == "application/json")
        return strip_fences(text), usage
    return send


def strip_fences(text: str | None) -> str | None:
    """The product's parsers expect bare JSON (Gemini JSON mode); some routes wrap it in a ``` block."""
    if text is None:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def reasoning_for(model: str) -> dict | None:
    """Match the product's thinking setting (Gemini 3.x thinking LOW) on OpenRouter; no thinking for 2.5 Flash-Lite."""
    if model.startswith("google/gemini-2.5"):
        return {"max_tokens": 0}
    if model.startswith("google/gemini-3"):
        return {"effort": "low"}
    if model.split("/")[0] in ("deepseek", "z-ai", "qwen", "xiaomi") or "gpt-oss" in model:
        return {"effort": "low"}  # thinking-by-default models otherwise spend the whole answer budget reasoning
    return None  # Haiku, Luna: provider default


def mp3_of(audio: Path) -> Path:
    """32 kbps mono MP3 next to the FLAC (OpenRouter takes base64 wav/mp3 input_audio)."""
    out = audio.with_suffix(".mp3")
    if not out.exists():
        import subprocess

        subprocess.run(["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error", "-i", str(audio), "-ac", "1",
                        "-b:a", "32k", str(out)], check=True)
    return out


def openrouter_audio(model: str, audio: Path, prompt: str, schema: dict, call_id: str, tag: str):
    mp3 = mp3_of(audio)
    msgs = [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": b64(mp3), "format": "mp3"}},
                                         {"type": "text", "text": prompt}]}]
    return pv.openrouter_chat(model, msgs, tag=tag, call_id=call_id, schema=schema, max_tokens=65_000,
                              temperature=0, reasoning=reasoning_for(model))


# ------------------------------------------------------------------ commands
def cmd_asr(a) -> None:
    kind, model = a.arm.split(":", 1)
    for cid in call_ids(a):
        out = RES / "asr" / a.arm.replace(":", "_").replace("/", "_") / a.variant / f"{cid}.json"
        if out.exists() and not a.force:
            continue
        audio = AUDIO / cid / f"{a.variant}.flac"
        if not audio.exists():
            print(cid, "skip: no audio yet", flush=True)
            continue
        t0 = time.time()
        if kind == "gemini":
            body = {"contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": "audio/flac", "data": b64(audio)}} if audio.stat().st_size < 18e6
                else {"file_data": {"mime_type": "audio/flac", "file_uri": pv.gemini_upload(audio)}},
                {"text": sh.ASR_PROMPT}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": sh.asr_schema(),
                                     "maxOutputTokens": 65_536, "temperature": 0}}
            if model.startswith("gemini-2.5"):
                body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
            else:
                body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "LOW"}
            text, usage, _ = pv.gemini_generate(model, body, tag=f"asr:{a.variant}", call_id=cid)
            try:
                segs = [{"speaker": s["speaker"], "start_ms": _ms(s["start"]), "end_ms": _ms(s["end"]),
                         "text": s["text"]} for s in parse_json_text(text or "")["segments"]]
                res = {"status": 200, "segments": segs, "usage": usage}
            except Exception as exc:
                res = {"status": "parse_error", "error": str(exc)[:200], "segments": [], "usage": usage}
        elif kind == "openrouter":
            text, usage, _ = openrouter_audio(model, audio, sh.ASR_PROMPT, sh.asr_schema(), cid, f"asr:{a.variant}")
            try:
                segs = [{"speaker": s["speaker"], "start_ms": _ms(s["start"]), "end_ms": _ms(s["end"]),
                         "text": s["text"]} for s in parse_json_text(text or "")["segments"]]
                res = {"status": 200, "segments": segs, "usage": usage}
            except Exception as exc:
                res = {"status": "parse_error", "error": str(exc)[:200], "segments": [], "usage": usage,
                       "raw_head": (text or "")[:300]}
        elif kind == "groq":
            res = pv.groq_transcribe(audio, model, cid)
        elif kind == "deepgram":
            res = pv.deepgram_transcribe(audio, cid, model)
        elif kind == "assemblyai":
            res = pv.assemblyai_transcribe(audio, cid, model)
        elif kind == "elevenlabs":
            res = pv.elevenlabs_transcribe(audio, cid)
        else:
            raise SystemExit(f"unknown arm {a.arm}")
        res["wall_s"] = round(time.time() - t0, 1)
        if res.get("status") == 200 and res.get("segments"):
            _write(out, res)
        else:  # not saved, so the next run retries it; the ledger keeps the error
            _write(out.with_suffix(".failed"), res)
        print(cid, a.arm, a.variant, res.get("status"), len(res.get("segments", [])), res["wall_s"], flush=True)


def cmd_text(a) -> None:
    for cid in call_ids(a):
        tdir = a.transcript.replace("/", "_")
        out = RES / "text" / a.shape / a.model.replace("/", "_") / tdir / f"run{a.run}" / f"{cid}.json"
        if out.exists() and not a.force:
            continue
        if a.transcript != "oracle" and not (RES / a.transcript / f"{cid}.json").exists():
            print(cid, "skip: no transcript in", a.transcript, flush=True)
            continue
        transcript = load_transcript(cid, a.transcript)
        send = make_send(a.model, cid, f"{a.shape}:{tdir}:r{a.run}")
        t0 = time.time()
        if a.shape == "today":
            from today import run_today

            result = run_today(transcript, send, CALL_DATE)
        else:
            system, user = sh.onepass_messages(transcript["segments"], CALL_DATE, version={"onepass2": 2, "onepass3": 3}.get(a.shape, 1))
            schema, max_out = sh.onepass_schema(), 16_000
            if a.shape == "brain4":  # round 4: the coaching lead's 18-dimension rubric in the same single pass
                system, schema, max_out = sh.BRAIN4_SYSTEM, sh.brain4_schema(), 24_000
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"responseMimeType": "application/json",
                                         "responseJsonSchema": schema, "maxOutputTokens": max_out,
                                         "thinkingConfig": {"thinkingLevel": "LOW"}}}
            text, usage = send(body, "onepass")
            try:
                result = {"onepass": parse_json_text(text or ""), "errors": []}
            except Exception as exc:
                result = {"errors": [f"onepass: {type(exc).__name__}"], "raw_head": (text or "")[:300]}
        result["wall_s"] = round(time.time() - t0, 1)
        result["transcript_segments"] = len(transcript["segments"])
        _write(out, result)
        print(cid, a.shape, a.model, a.transcript, "errors:", len(result.get("errors", [])), result["wall_s"], flush=True)


def cmd_audio1(a) -> None:
    for cid in call_ids(a):
        out = RES / "audio1" / a.model.replace("/", "_") / a.variant / f"run{a.run}" / f"{cid}.json"
        if out.exists() and not a.force:
            continue
        audio = AUDIO / cid / f"{a.variant}.flac"
        if not audio.exists():
            print(cid, "skip: no audio yet", flush=True)
            continue
        prompt = f"Call date: {CALL_DATE}.\n" + sh.AUDIO_ONECALL_PROMPT
        t0 = time.time()
        if a.model.startswith("google/"):
            text, usage, _ = openrouter_audio(a.model, audio, prompt, sh.audio_onecall_schema(), cid,
                                              f"audio1:{a.variant}:r{a.run}")
        else:
            part = ({"inline_data": {"mime_type": "audio/flac", "data": b64(audio)}} if audio.stat().st_size < 18e6
                    else {"file_data": {"mime_type": "audio/flac", "file_uri": pv.gemini_upload(audio)}})
            body = {"contents": [{"role": "user", "parts": [part, {"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json",
                                         "responseJsonSchema": sh.audio_onecall_schema(),
                                         "maxOutputTokens": 65_536, "temperature": 0}}
            body["generationConfig"]["thinkingConfig"] = ({"thinkingBudget": 0} if a.model.startswith("gemini-2.5")
                                                          else {"thinkingLevel": "LOW"})
            text, usage, _ = pv.gemini_generate(a.model, body, tag=f"audio1:{a.variant}:r{a.run}", call_id=cid)
        try:
            result = {"onepass": parse_json_text(text or ""), "errors": [], "usage": usage}
        except Exception as exc:
            result = {"errors": [f"audio1: {type(exc).__name__}"], "usage": usage, "raw_head": (text or "")[:300]}
        result["wall_s"] = round(time.time() - t0, 1)
        _write(out, result)
        print(cid, "audio1", a.model, a.variant, "errors:", len(result["errors"]), result["wall_s"], flush=True)


def system_facts(result: dict) -> list[str]:
    if "onepass" in result:
        return [f"{f.get('type')}: {f.get('value')}" + (" (withdrawn)" if f.get("withdrawn") else "")
                for f in result["onepass"].get("facts", []) if isinstance(f, dict)]
    from today import facts_for_judging

    return facts_for_judging(result)


def cmd_judge(a) -> None:
    rdir = Path(a.result)
    for path in sorted(rdir.glob("fx-*.json")):
        cid = path.stem
        out = rdir / "judge" / a.judge.replace("/", "_") / f"{cid}.json"
        if out.exists() and not a.force:
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        facts = json.loads((CALLS / cid / "facts.json").read_text(encoding="utf-8"))
        gt = [{"id": f["id"], "type": f["type"], "slot": f.get("slot"), "value": f["value"],
               "normalized": f.get("normalized")} for f in facts]
        sysf = system_facts(result)
        transcript = oracle_transcript(cid)
        user = ("Ground-truth facts:\n" + json.dumps(gt, ensure_ascii=False) + "\n\nSystem facts (index: fact):\n"
                + "\n".join(f"{i}: {s}" for i, s in enumerate(sysf)) + "\n\nTranscript:\n"
                + sh.transcript_lines(transcript["segments"]))
        body = {"systemInstruction": {"parts": [{"text": sh.JUDGE_SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": sh.judge_schema(),
                                     "maxOutputTokens": 16_000, "temperature": 0,
                                     "thinkingConfig": {"thinkingLevel": "LOW"}}}
        text, usage = make_send(a.judge, cid, "judge")(body, "judge")
        try:
            verdict = parse_json_text(text or "")
        except Exception as exc:
            verdict = {"error": f"{type(exc).__name__}", "raw_head": (text or "")[:300]}
        verdict["n_system_facts"] = len(sysf)
        verdict["n_ground_truth"] = len(gt)
        _write(out, verdict)
        print(cid, "judged by", a.judge, "gt", len(gt), "sys", len(sysf), flush=True)


RJUDGE_SYSTEM = """You are a strict benchmark judge of sales-coaching reports. You get the planted coaching truths of a
call (what the salesperson really did well or badly, written by the call's author), the system's coaching output, and
the transcript. For each truth decide whether the system's output identifies it: "covered" (same point, same
moment or clearly the same behaviour), "partial" (related but vague or incomplete) or "not_covered".
Then list the system's coaching claims that the transcript contradicts or that rest on things that never happened
("false_claims", each one short sentence). Do not count style or wording differences. Return JSON only."""


def rjudge_schema() -> dict:
    return {"type": "object", "properties": {
        "truths": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "verdict": {"type": "string", "enum": ["covered", "partial", "not_covered"]}},
            "required": ["id", "verdict"]}},
        "false_claims": {"type": "array", "items": {"type": "string"}}}, "required": ["truths", "false_claims"]}


def system_coaching(result: dict) -> dict:
    if "onepass" in result:
        out = {"report": result["onepass"].get("report"), "pointers": result["onepass"].get("pointers")}
        for k in ("dimensions", "coach_notes"):  # brain4: the 18 rubric dimensions and the coach's moment notes
            if result["onepass"].get(k):
                out[k] = result["onepass"][k]
        return out
    return {"report": result.get("c5"), "pointers": (result.get("pointer_review") or {}).get("pointers")}


def cmd_rjudge(a) -> None:
    rdir = Path(a.result)
    for path in sorted(rdir.glob("fx-*.json")):
        cid = path.stem
        out = rdir / "rjudge" / a.judge.replace("/", "_") / f"{cid}.json"
        if out.exists() and not a.force:
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        plan = json.loads((CALLS / cid / "plan.json").read_text(encoding="utf-8"))
        truths = [{"id": k["id"], "kind": k["kind"], "statement": k["statement"]} for k in plan.get("coaching_truths", [])]
        coaching = system_coaching(result)
        if not coaching.get("report"):
            _write(out, {"error": "no report", "n_truths": len(truths)})
            continue
        user = ("Coaching truths:\n" + json.dumps(truths, ensure_ascii=False) + "\n\nSystem coaching output:\n"
                + json.dumps(coaching, ensure_ascii=False)[:60000] + "\n\nTranscript:\n"
                + sh.transcript_lines(oracle_transcript(cid)["segments"]))
        body = {"systemInstruction": {"parts": [{"text": RJUDGE_SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": rjudge_schema(),
                                     "maxOutputTokens": 8_000, "temperature": 0,
                                     "thinkingConfig": {"thinkingLevel": "LOW"}}}
        text, _ = make_send(a.judge, cid, "judge")(body, "rjudge")
        try:
            verdict = parse_json_text(text or "")
        except Exception as exc:
            verdict = {"error": type(exc).__name__}
        verdict["n_truths"] = len(truths)
        _write(out, verdict)
        print(cid, "report judged by", a.judge, flush=True)


RETAIN_SYSTEM = """You check whether critical facts survived speech-to-text. You get facts from a call's ground truth
(each with the words actually spoken) and an automatic transcript of the call, which may write Hindi/Marathi in
Devanagari or Latin script, English words in either script, and numbers as digits or words. For each fact decide:
- "present": a reader of this transcript would recover the exact value (same name as it sounds, same amount, date,
  time, quantity), whatever the script or number format;
- "garbled": the place is there but the value is wrong or unreadable (wrong digit, wrong name, cut words);
- "missing": the transcript does not contain it.
Be strict on numbers and names. Return JSON only."""


def cmd_retain(a) -> None:
    rdir = Path(a.result)
    schema = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "verdict": {"type": "string", "enum": ["present", "garbled", "missing"]}},
        "required": ["id", "verdict"]}}}, "required": ["facts"]}
    for path in sorted(rdir.glob("fx-*.json")):
        cid = path.stem
        out = rdir / "retain" / a.judge.replace("/", "_") / f"{cid}.json"
        if out.exists() and not a.force:
            continue
        res = json.loads(path.read_text(encoding="utf-8"))
        facts = [f for f in json.loads((CALLS / cid / "facts.json").read_text(encoding="utf-8")) if f.get("critical")]
        crit = [{"id": f["id"], "type": f["type"], "value": f["value"], "normalized": f.get("normalized"),
                 "spoken_as": f.get("evidence")} for f in facts]
        hyp = "\n".join(f"{s.get('speaker')}: {s.get('text')}" for s in res.get("segments", []))
        if not hyp:
            _write(out, {"error": "empty transcript", "n": len(crit)})
            continue
        user = "Critical facts:\n" + json.dumps(crit, ensure_ascii=False) + "\n\nAutomatic transcript:\n" + hyp
        body = {"systemInstruction": {"parts": [{"text": RETAIN_SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema,
                                     "maxOutputTokens": 8_000, "temperature": 0,
                                     "thinkingConfig": {"thinkingLevel": "LOW"}}}
        text, _ = make_send(a.judge, cid, "judge")(body, "retain")
        try:
            v = parse_json_text(text or "")
        except Exception as exc:
            v = {"error": type(exc).__name__}
        v["n"] = len(crit)
        _write(out, v)
        print(cid, "retention judged by", a.judge, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("asr", "text", "audio1", "judge", "rjudge", "retain"):
        p = sub.add_parser(name)
        p.add_argument("--calls", nargs="*")
        p.add_argument("--force", action="store_true")
        p.add_argument("--run", type=int, default=1)
    sub.choices["asr"].add_argument("--arm", required=True)
    sub.choices["asr"].add_argument("--variant", default="phone_8k")
    sub.choices["text"].add_argument("--shape", choices=["today", "onepass", "onepass2", "onepass3", "brain4"], required=True)
    sub.choices["text"].add_argument("--model", required=True)
    sub.choices["text"].add_argument("--transcript", default="oracle")
    sub.choices["audio1"].add_argument("--model", required=True)
    sub.choices["audio1"].add_argument("--variant", default="phone_8k")
    sub.choices["judge"].add_argument("--result", required=True)
    sub.choices["judge"].add_argument("--judge", default="gemini-3.8-flash")
    sub.choices["rjudge"].add_argument("--result", required=True)
    sub.choices["rjudge"].add_argument("--judge", default="gemini-3.8-flash")
    sub.choices["retain"].add_argument("--result", required=True)
    sub.choices["retain"].add_argument("--judge", default="gemini-3.8-flash")
    a = ap.parse_args()
    try:
        {"asr": cmd_asr, "text": cmd_text, "audio1": cmd_audio1, "judge": cmd_judge, "rjudge": cmd_rjudge,
         "retain": cmd_retain}[a.cmd](a)
    except BudgetExceeded as exc:
        print("STOP:", exc, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

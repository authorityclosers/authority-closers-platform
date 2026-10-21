"""Provider clients for the benchmark (fictional calls only). Each call logs one ledger row."""

from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any

from common import (PRICES, STT_PER_MIN, BUDGET_OPENROUTER_USD, BudgetExceeded, b64, http_json, key,
                    ledger_append, spent)

GEMINI = "https://generativelanguage.googleapis.com"


def _audio_seconds(path: Path) -> float:
    import subprocess

    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# ---------------------------------------------------------------- Gemini (bench project, free tier)
def gemini_upload(path: Path) -> str:
    """Files API resumable upload; returns the file URI."""
    k = key("GEMINI_API_KEY")
    mime = mimetypes.guess_type(path.name)[0] or "audio/flac"
    size = path.stat().st_size
    import urllib.request

    req = urllib.request.Request(
        f"{GEMINI}/upload/v1beta/files", method="POST",
        data=json.dumps({"file": {"display_name": path.stem}}).encode(),
        headers={"x-goog-api-key": k, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": mime,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        upload_url = r.headers["X-Goog-Upload-URL"]
    req = urllib.request.Request(upload_url, method="POST", data=path.read_bytes(),
                                 headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize",
                                          "Content-Length": str(size)})
    with urllib.request.urlopen(req, timeout=600) as r:
        info = json.loads(r.read())
    f = info["file"]
    for _ in range(60):  # wait until ACTIVE
        if f.get("state") in (None, "ACTIVE"):
            break
        time.sleep(2)
        _, f, _ = http_json(f"{GEMINI}/v1beta/{f['name']}", headers={"x-goog-api-key": k})
    return f["uri"]


def gemini_generate(model: str, body: dict[str, Any], *, tag: str, call_id: str) -> tuple[str | None, dict, float]:
    k = key("GEMINI_API_KEY")
    status, resp, dt = http_json(f"{GEMINI}/v1beta/models/{model}:generateContent", body,
                                 {"x-goog-api-key": k}, timeout=900)
    u = resp.get("usageMetadata", {}) if isinstance(resp, dict) else {}
    audio_in = sum(d.get("tokenCount", 0) for d in u.get("promptTokensDetails", []) if d.get("modality") == "AUDIO")
    tin = int(u.get("promptTokenCount", 0))
    tout = int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
    cached = int(u.get("cachedContentTokenCount", 0))
    p_in, p_out, p_audio = PRICES.get(model, (0.75, 3.75, 0.75))
    list_usd = ((tin - audio_in - cached) * p_in + cached * p_in * 0.1 + audio_in * (p_audio or p_in)
                + tout * p_out) / 1e6
    text = None
    finish = None
    try:
        cand = resp["candidates"][0]
        finish = cand.get("finishReason")
        text = "".join(p.get("text", "") for p in cand["content"]["parts"] if not p.get("thought"))
    except (KeyError, IndexError, TypeError):
        pass
    usage = {"in": tin, "out": tout, "audio_in": audio_in, "cached": cached, "thoughts": u.get("thoughtsTokenCount", 0)}
    ledger_append({"provider": "gemini-free", "model": model, "tag": tag, "call": call_id, "status": status,
                   "finish": finish, **usage, "list_usd": round(list_usd, 6), "billed_usd": 0.0,
                   "latency_s": round(dt, 2), "error": None if status == 200 else str(resp)[:300]})
    return text, {**usage, "list_usd": list_usd, "status": status, "finish": finish}, dt


# ---------------------------------------------------------------- OpenRouter ($20 credit)
def openrouter_chat(model: str, messages: list[dict], *, tag: str, call_id: str, schema: dict | None = None,
                    max_tokens: int = 12000, temperature: float | None = None,
                    reasoning: dict | None = None, json_mode: bool = False) -> tuple[str | None, dict, float]:
    if spent("openrouter") >= BUDGET_OPENROUTER_USD:
        raise BudgetExceeded(f"OpenRouter budget ${BUDGET_OPENROUTER_USD} reached")
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                            "usage": {"include": True},
                            # reputable hosts only: no fp4 small hosts, no providers that train on prompts
                            "provider": {"data_collection": "deny", "allow_fallbacks": True,
                                         "quantizations": ["fp8", "bf16", "fp16", "fp32", "unknown"]}}
    if schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "answer", "strict": False, "schema": schema}}
    elif json_mode:
        body["response_format"] = {"type": "json_object"}
    if model.startswith("google/"):  # AI Studio list prices (Vertex is ~10% dearer); fall back if it is busy
        body["provider"]["order"] = ["google-ai-studio"]
    if os.environ.get("BENCH_STRICT") == "1":
        # real calls (owner-approved 21 Oct): Google AI Studio or OpenAI only, zero data retention, no fallback hosts
        if not model.startswith(("google/", "openai/")):
            raise SystemExit(f"BENCH_STRICT: {model} is not an approved provider for real calls")
        # zero-retention endpoints on OpenRouter: Gemini only on Google Vertex; GPT-6 Luna only on Azure
        body["provider"].update({"zdr": True, "allow_fallbacks": False,
                                 "only": ["google-vertex"] if model.startswith("google/") else
                                 os.environ.get("BENCH_OPENAI_HOSTS", "openai").split(",")})
        body["provider"].pop("order", None)
    if temperature is not None:
        body["temperature"] = temperature
    if reasoning is not None:
        body["reasoning"] = reasoning
    status, resp, dt = http_json("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": f"Bearer {key('OPENROUTER_API_KEY')}",
                                  "X-Title": "AC analysis-cost research"}, timeout=900)
    u = resp.get("usage", {}) if isinstance(resp, dict) else {}
    tin, tout = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
    cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0)
    billed = float(u.get("cost", 0) or 0)
    p_in, p_out, _ = PRICES.get(model, (0, 0, None))
    list_usd = (tin * p_in + tout * p_out) / 1e6
    text, finish, host = None, None, resp.get("provider") if isinstance(resp, dict) else None
    try:
        ch = resp["choices"][0]
        finish = ch.get("finish_reason")
        text = ch["message"].get("content")
    except (KeyError, IndexError, TypeError):
        pass
    usage = {"in": tin, "out": tout, "cached": cached, "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
    ledger_append({"provider": "openrouter", "model": model, "host": host, "tag": tag, "call": call_id,
                   "status": status, "finish": finish, **usage, "list_usd": round(list_usd, 6),
                   "billed_usd": round(billed, 6), "latency_s": round(dt, 2),
                   "error": None if status == 200 else str(resp)[:300]})
    return text, {**usage, "list_usd": list_usd, "billed_usd": billed, "status": status, "finish": finish,
                  "host": host}, dt


# ---------------------------------------------------------------- speech to text
def _multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _stt_log(arm: str, call_id: str, status: int, seconds: float, dt: float, resp: Any, billed: float = 0.0) -> None:
    ledger_append({"provider": arm.split("/")[0], "model": arm, "tag": "stt", "call": call_id, "status": status,
                   "audio_s": round(seconds, 1), "list_usd": round(STT_PER_MIN.get(arm, 0) * seconds / 60, 6),
                   "billed_usd": billed, "latency_s": round(dt, 2),
                   "error": None if status == 200 else str(resp)[:300]})


def groq_transcribe(path: Path, model: str, call_id: str, language: str | None = None) -> dict:
    fields = {"model": model, "response_format": "verbose_json", "timestamp_granularities[]": "segment",
              "temperature": "0"}
    if language:
        fields["language"] = language
    raw, ctype = _multipart(fields, "file", path)
    status, resp, dt = http_json("https://api.groq.com/openai/v1/audio/transcriptions", raw=raw,
                                 headers={"Authorization": f"Bearer {key('GROQ_API_KEY')}", "Content-Type": ctype})
    _stt_log(f"groq/{model}", call_id, status, _audio_seconds(path), dt, resp)
    segs = [{"speaker": "speaker_0", "start_ms": int(s["start"] * 1000), "end_ms": int(s["end"] * 1000),
             "text": s["text"].strip()} for s in resp.get("segments", [])] if status == 200 else []
    return {"status": status, "segments": segs, "latency_s": dt, "language": resp.get("language")}


def deepgram_transcribe(path: Path, call_id: str, model: str = "nova-3") -> dict:
    q = (f"model={model}&language=multi&diarize=true&utterances=true&smart_format=true&punctuate=true"
         "&mip_opt_out=true")
    status, resp, dt = http_json(f"https://api.deepgram.com/v1/listen?{q}", raw=path.read_bytes(),
                                 headers={"Authorization": f"Token {key('DEEPGRAM_API_KEY')}",
                                          "Content-Type": mimetypes.guess_type(path.name)[0] or "audio/flac"})
    _stt_log(f"deepgram/{model}", call_id, status, _audio_seconds(path), dt, resp)
    segs = []
    if status == 200:
        for u in resp.get("results", {}).get("utterances", []):
            segs.append({"speaker": f"speaker_{u.get('speaker', 0)}", "start_ms": int(u["start"] * 1000),
                         "end_ms": int(u["end"] * 1000), "text": u["transcript"]})
    return {"status": status, "segments": segs, "latency_s": dt}


def assemblyai_transcribe(path: Path, call_id: str, model: str = "universal-2") -> dict:
    h = {"Authorization": key("ASSEMBLYAI_API_KEY")}
    t0 = time.time()
    status, up, _ = http_json("https://api.assemblyai.com/v2/upload", raw=path.read_bytes(),
                              headers={**h, "Content-Type": "application/octet-stream"})
    if status != 200:
        _stt_log(f"assemblyai/{model}", call_id, status, _audio_seconds(path), time.time() - t0, up)
        return {"status": status, "segments": []}
    status, job, _ = http_json("https://api.assemblyai.com/v2/transcript",
                               {"audio_url": up["upload_url"], "speech_models": [model], "speaker_labels": True,
                                "language_detection": True}, h)
    while status == 200 and job.get("status") not in ("completed", "error"):
        time.sleep(5)
        status, job, _ = http_json(f"https://api.assemblyai.com/v2/transcript/{job['id']}", headers=h)
    dt = time.time() - t0
    ok = status == 200 and job.get("status") == "completed"
    _stt_log(f"assemblyai/{model}", call_id, 200 if ok else (status or 500), _audio_seconds(path), dt, job)
    segs = [{"speaker": f"speaker_{u.get('speaker', 'A')}", "start_ms": int(u["start"]), "end_ms": int(u["end"]),
             "text": u["text"]} for u in (job.get("utterances") or [])] if ok else []
    return {"status": 200 if ok else status, "segments": segs, "latency_s": dt,
            "language": job.get("language_code")}


def elevenlabs_transcribe(path: Path, call_id: str) -> dict:
    fields = {"model_id": "scribe_v2", "timestamps_granularity": "word", "diarize": "true",
              "tag_audio_events": "false"}
    raw, ctype = _multipart(fields, "file", path)
    status, resp, dt = http_json("https://api.elevenlabs.io/v1/speech-to-text", raw=raw,
                                 headers={"xi-api-key": key("ELEVENLABS_API_KEY"), "Content-Type": ctype})
    _stt_log("elevenlabs/scribe_v2", call_id, status, _audio_seconds(path), dt, resp)
    segs: list[dict] = []
    if status == 200:  # merge words like the product does: same speaker, gap <= 1.5 s, < 700 chars
        for w in resp.get("words", []):
            if w.get("type") == "spacing":
                continue
            spk = w.get("speaker_id") or "unattributed"
            st, en, tx = int(w["start"] * 1000), int(w["end"] * 1000), w["text"]
            if segs and segs[-1]["speaker"] == spk and st - segs[-1]["end_ms"] <= 1500 and len(segs[-1]["text"]) < 700:
                segs[-1]["text"] += " " + tx
                segs[-1]["end_ms"] = en
            else:
                segs.append({"speaker": spk, "start_ms": st, "end_ms": en, "text": tx})
    return {"status": status, "segments": segs, "latency_s": dt, "language": resp.get("language_code")}


# ------------------------------------------------------------------ OpenAI direct (bench project, fictional data only)
OPENAI_BUDGET_USD = float(os.environ.get("BENCH_OPENAI_BUDGET", "4.5"))  # the bench project's hard limit is $5
OPENAI_PRICES = {"gpt-6-luna": (0.10, 0.50, 0.01)}  # USD per million: input, output, cached input (standard tier)


def openai_chat(model: str, messages: list[dict], *, tag: str, call_id: str, schema: dict | None = None,
                max_tokens: int = 32000, reasoning_effort: str | None = None,
                service_tier: str | None = None) -> tuple[str | None, dict, float]:
    """Chat completions on OpenAI's API with store=false; Flex tier on request (half price, slower)."""
    if spent("openai") >= OPENAI_BUDGET_USD:
        raise BudgetExceeded(f"OpenAI budget ${OPENAI_BUDGET_USD} reached")
    body: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens": max_tokens,
                            "store": False}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if service_tier:
        body["service_tier"] = service_tier
    schema_mode = "none"
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "strict": False,
                                                                           "schema": schema}}
        schema_mode = "schema"
    hdrs = {"Authorization": f"Bearer {key('OPENAI_API_KEY')}"}
    status, resp, dt = http_json("https://api.openai.com/v1/chat/completions", body, hdrs, timeout=1800)
    if status == 400 and schema is not None:  # schema refused as a constraint: send it as text, JSON mode
        body["response_format"] = {"type": "json_object"}
        body["messages"] = [dict(messages[0], content=messages[0]["content"]
                                 + "\n\nReturn ONE JSON object matching this JSON schema:\n" + json.dumps(schema))] + messages[1:]
        schema_mode = "prompt"
        status, resp, dt = http_json("https://api.openai.com/v1/chat/completions", body, hdrs, timeout=1800)
    u = resp.get("usage", {}) if isinstance(resp, dict) else {}
    tin, tout = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
    cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0)
    p_in, p_out, p_cache = OPENAI_PRICES.get(model, (0.0, 0.0, 0.0))
    tier = (resp.get("service_tier") if isinstance(resp, dict) else None) or service_tier or "default"
    factor = 0.5 if tier == "flex" else 1.0
    usd = ((tin - cached) * p_in + cached * p_cache + tout * p_out) / 1e6 * factor
    text, finish = None, None
    try:
        ch = resp["choices"][0]
        finish = ch.get("finish_reason")
        text = ch["message"].get("content")
    except (KeyError, IndexError, TypeError):
        pass
    usage = {"in": tin, "out": tout, "cached": cached,
             "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
    ledger_append({"provider": "openai", "model": f"openai/{model}", "host": "openai", "tier": tier, "tag": tag,
                   "call": call_id, "status": status, "finish": finish, "schema_mode": schema_mode, **usage,
                   "list_usd": round(usd, 6), "billed_usd": round(usd, 6), "latency_s": round(dt, 2),
                   "error": None if status == 200 else str(resp)[:300]})
    return text, {**usage, "list_usd": usd, "status": status, "finish": finish, "tier": tier,
                  "schema_mode": schema_mode}, dt

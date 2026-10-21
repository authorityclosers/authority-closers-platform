"""Shape (a): today's multi-pass pipeline, rebuilt from the product's own prompt builders (read-only import of
packages/python from the dev workbench), sent to the model under test.

C4 facts (facts-v2, 1,400-token cap, chunked like the product) -> C5 report (coaching-v3, detailed overview, 8,000
cap) -> pointer review (27 pointers) -> call-data fast extract -> call-data deep extract + per-segment labels.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable

from ac_platform.call_data import classifier as cl
from ac_platform.call_data import extraction as ex
from ac_platform.call_data import taxonomy as tx
from ac_platform.conversation_intelligence import inference_tasks as it
from ac_platform.conversation_intelligence import pointer_review as pr
from ac_platform.conversation_intelligence import reports as rp

Send = Callable[[dict, str], tuple[str | None, dict]]  # (gemini-style body, tag) -> (text, usage)


def _gemini_body(system: str, user: str, *, schema: dict | None, max_out: int, temperature: float | None) -> dict:
    cfg: dict[str, Any] = {"candidateCount": 1, "maxOutputTokens": max_out, "responseMimeType": "application/json",
                           "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False}}
    if schema is not None:
        cfg["responseJsonSchema"] = schema
    if temperature is not None:
        cfg["temperature"] = temperature
    return {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": cfg}


def _json(text: str | None) -> Any:
    from common import parse_json_text

    if not text:
        raise ValueError("empty")
    return parse_json_text(text)


def run_today(transcript: dict, send: Send, call_date: str) -> dict[str, Any]:
    out: dict[str, Any] = {"errors": []}
    # ---- C4 facts, chunked exactly as the product does
    prepared = it.prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash",
                                      max_completion_tokens=1_400, prompt_revision="facts-v2")
    by_id = {s["id"]: s for s in transcript["segments"]}
    packets, observations = [], []
    for p in prepared:
        body = json.loads(p.payload)
        text, _ = send(body, f"C4.{p.chunk_index}")
        segs = [by_id[i] for i in p.covered_segment_ids]
        chunk = rp.TranscriptChunk(ordinal=p.chunk_index, total=p.chunk_count, segments=tuple(segs),
                                   start_ms=segs[0]["start_ms"], end_ms=segs[-1]["end_ms"],
                                   source_sha256=transcript["source_sha256"],
                                   transcript_revision=transcript["revision"])
        try:
            packet = rp.parse_fact_packet(text or "", transcript, chunk=chunk, compact=True,
                                          max_completion_tokens=1_400)
            packets.append(packet)
            raw = _json(text)
            observations += [o.get("fact") for o in raw.get("observations", []) if isinstance(o, dict)]
        except Exception as exc:  # a malformed answer is a quality result, recorded
            out["errors"].append(f"C4.{p.chunk_index}: {type(exc).__name__}: {str(exc)[:120]}")
    out["c4_observations"] = observations
    # ---- C5 report
    if packets and len(packets) == len(prepared):
        try:
            c5 = it.prepare_coaching_input(transcript, packets, provider="gemini", model="gemini-3.8-flash",
                                           # 8,000 (the Flash ceiling): production C5 outputs already exceed 3,200
                                           # tokens, and 3,200 fails the prompt budget for calls over ~15 min
                                           max_completion_tokens=8_000, output_profile="detailed",
                                           coaching_prompt_revision="coaching-v3")
            text, _ = send(json.loads(c5.payload), "C5")
            out["c5"] = _json(text)
        except Exception as exc:
            out["errors"].append(f"C5: {type(exc).__name__}: {str(exc)[:160]}")
    else:
        out["errors"].append("C5: skipped (C4 incomplete)")
    # ---- call data fast
    segments = ex.segments_from_transcript(transcript)
    roles: dict[str, str] = {}
    system, user = ex.build_prompt(segments, types=tx.FAST_TYPES, call_date=call_date)
    text, _ = send(_gemini_body(system, user, schema=ex.response_schema(tx.FAST_TYPES), max_out=12_000,
                                temperature=0.1), "fast")
    try:
        fast = _json(text)
        out["fast"] = fast
        roles = ex.parse_roles(fast, segments)
    except Exception as exc:
        out["errors"].append(f"fast: {type(exc).__name__}")
    # ---- pointer review
    system, user = pr.build_prompt(transcript["segments"], {k: v for k, v in roles.items()})
    text, _ = send(pr.gemini_body(system, user), "pointer_review")
    try:
        out["pointer_review"] = _json(text)
    except Exception as exc:
        out["errors"].append(f"pointer_review: {type(exc).__name__}")
    # ---- call data deep: extract + segment labels
    system, user = ex.build_prompt(segments, types=tx.DEEP_EXTRACT_TYPES, call_date=call_date)
    text, _ = send(_gemini_body(system, user, schema=ex.response_schema(tx.DEEP_EXTRACT_TYPES), max_out=12_000,
                                temperature=0.1), "deep_extract")
    try:
        out["deep"] = _json(text)
    except Exception as exc:
        out["errors"].append(f"deep_extract: {type(exc).__name__}")
    labels = []
    for start, end in cl.chunks(segments):
        system, user = cl.build_prompt(segments, start, end, roles=roles)
        text, _ = send(_gemini_body(system, user, schema=cl.response_schema(), max_out=12_000, temperature=0.1),
                       f"deep_labels.{start}")
        try:
            labels += _json(text).get("labels", [])
        except Exception as exc:
            out["errors"].append(f"deep_labels.{start}: {type(exc).__name__}")
    out["deep_labels"] = labels
    out["roles"] = roles
    return out


def facts_for_judging(result: dict[str, Any]) -> list[str]:
    """Flatten today's facts (fast + deep typed facts, then C4 observations) to judge lines."""
    lines = []
    for src in ("fast", "deep"):
        for f in (result.get(src) or {}).get("facts", []) or []:
            if isinstance(f, dict):
                lines.append(f"{f.get('type')}: {json.dumps(f.get('value'), ensure_ascii=False)}")
    lines += [f"observation: {o}" for o in result.get("c4_observations", []) if o]
    return lines


def to_messages(body: dict) -> tuple[list[dict], dict | None, int]:
    """Gemini body -> OpenAI-style messages, schema, max tokens (for non-Gemini models)."""
    body = copy.deepcopy(body)
    system = "".join(p.get("text", "") for p in body.get("systemInstruction", {}).get("parts", []))
    user = "".join(p.get("text", "") for c in body.get("contents", []) for p in c.get("parts", []))
    cfg = body.get("generationConfig", {})
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    return msgs, cfg.get("responseJsonSchema"), int(cfg.get("maxOutputTokens", 8000))

#!/usr/bin/env python3
"""Intelligibility check of rendered audio: transcribe with faster-whisper and compare with the script.

Usage: qa_roundtrip.py --calls calls --audio audio --model small --seconds 120 [--variant clean_16k|phone_8k]
Prints per call: CER (characters, punctuation and case removed) over the first --seconds of audio, using the
segments.json timings to pick the reference turns. Writes <audio>/<call>/qa_<variant>_<model>.json.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_V = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
      "ऑ": "o", "ॲ": "e"}
_M = {"ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
      "ॉ": "o", "ॅ": "e", "ं": "n", "ँ": "n", "ः": "h", "़": ""}
_C = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ",
              "k kh g gh n ch chh j jh n t th d dh n t th d dh n p ph b bh m y r l v sh sh s h l".split()))
_D = dict(zip("०१२३४५६७८९", "0123456789"))


def translit(s: str) -> str:
    """Rough Devanagari -> Latin (inherent a, matras, virama, final-schwa deletion) so that English words written
    in either script and Hindi/Marathi words compare on one alphabet. Approximate; used only for tCER."""
    out, i = [], 0
    s = unicodedata.normalize("NFC", s)
    while i < len(s):
        ch = s[i]
        if ch in _C:
            out.append(_C[ch])
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == "्":
                i += 2
                continue
            if nxt in _M and nxt not in "ंँः़":
                i += 1
                continue
            out.append("a")
        elif ch in _M:
            out.append(_M[ch])
        elif ch in _V:
            out.append(_V[ch])
        elif ch in _D:
            out.append(_D[ch])
        elif ch == "्":
            pass
        else:
            out.append(ch)
        i += 1
    words = "".join(out).lower().split()
    return " ".join(w[:-1] if len(w) > 2 and w.endswith("a") and not w.endswith("aa") else w for w in words)


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref).replace(" ", ""), norm(hyp).replace(" ", "")
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / len(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=Path, default=Path("calls"))
    ap.add_argument("--audio", type=Path, default=Path("audio"))
    ap.add_argument("--model", default="small")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--variant", default="clean_16k")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=4)
    for d in sorted(p for p in a.audio.iterdir() if p.is_dir()):
        if a.only and d.name not in a.only:
            continue
        script = json.loads((a.calls / d.name / "script.json").read_text(encoding="utf-8"))
        text_by_id = {t["id"]: t["text"] for t in script["turns"]}
        segs = json.loads((d / "segments.json").read_text(encoding="utf-8"))
        limit_ms = a.seconds * 1000
        ref = " ".join(text_by_id[s["turn_id"]] for s in segs if s["end_ms"] <= limit_ms)
        t0 = time.time()
        out, info = model.transcribe(str(d / f"{a.variant}.flac"), beam_size=1, vad_filter=False,
                                     clip_timestamps=[0, a.seconds])
        hyp_parts, hyp_end = [], 0.0
        for seg in out:
            if seg.end * 1000 > limit_ms + 1500:
                break
            hyp_parts.append(seg.text)
            hyp_end = seg.end
        hyp = " ".join(hyp_parts)
        res = {"call": d.name, "variant": a.variant, "model": a.model, "language": info.language,
               "lang_prob": round(info.language_probability, 2), "seconds": a.seconds,
               "cer": round(cer(ref, hyp), 3), "tcer": round(cer(translit(ref), translit(hyp)), 3), "wall_s": round(time.time() - t0, 1),
               "ref_head": ref[:160], "hyp_head": hyp[:160]}
        (d / f"qa_{a.variant}_{a.model}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
        print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

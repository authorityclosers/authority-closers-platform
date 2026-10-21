#!/usr/bin/env python3
"""Self-hosted ASR arm: faster-whisper on a 4-vCPU CPU runner (int8). Writes the harness segment format plus the
real-time factor, so the cost of self-hosting can be computed from runner-hours.

Usage: asr_local.py --audio <dir with <call>/phone_8k.flac> --model large-v3-turbo --out <dir> [--variant phone_8k]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--variant", default="phone_8k")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    t_load = time.time()
    model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=4)
    load_s = time.time() - t_load
    for d in sorted({f.parent for f in a.audio.rglob(f"{a.variant}.flac")} - {f.parent for f in a.audio.rglob("variant-*/*/*")}):
        t0 = time.time()
        segs_iter, info = model.transcribe(str(d / f"{a.variant}.flac"), beam_size=1, vad_filter=True,
                                           condition_on_previous_text=False)
        segs = [{"speaker": "speaker_0", "start_ms": int(s.start * 1000), "end_ms": int(s.end * 1000),
                 "text": s.text.strip()} for s in segs_iter]
        wall = time.time() - t0
        res = {"status": 200, "segments": segs, "language": info.language,
               "language_probability": round(info.language_probability, 3), "audio_s": round(info.duration, 1),
               "wall_s": round(wall, 1), "rtf": round(wall / max(info.duration, 1e-6), 3), "model_load_s": round(load_s, 1),
               "runner": "github ubuntu-latest 4 vCPU, int8, beam 1, VAD"}
        out = a.out / f"local_faster-whisper-{a.model}" / a.variant / f"{d.name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: res[k] for k in ("audio_s", "wall_s", "rtf", "language")}), d.name, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Real human speech cross-check: build one ~12-minute pseudo-call per language from Google FLEURS test utterances
(CC-BY-4.0, ungated), in the benchmark's call/audio layout, so every ASR arm can be scored on real voices.

Usage: realspeech.py --lang hi_in mr_in --n 70 --out out/
Writes out/calls/rs-fleurs-<lang>/{plan,script}.json and out/audio/rs-fleurs-<lang>/{clean_16k,phone_8k}.flac,
segments.json.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

SR = 16000
BASE = "https://huggingface.co/datasets/google/fleurs/resolve/refs%2Fconvert%2Fparquet/{lang}/test/0000.parquet"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", nargs="+", default=["hi_in", "mr_in"])
    ap.add_argument("--n", type=int, default=70)
    ap.add_argument("--out", type=Path, default=Path("out"))
    a = ap.parse_args()
    import pyarrow.parquet as pq
    import urllib.request

    for lang in a.lang:
        cid = f"rs-fleurs-{lang.split('_')[0]}"
        with tempfile.TemporaryDirectory() as td:
            pf = Path(td) / "t.parquet"
            urllib.request.urlretrieve(BASE.format(lang=lang), pf)
            table = pq.read_table(pf).to_pylist()
        seen, rows = set(), []
        for r in table:  # one recording per sentence id, alternating genders where possible
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            rows.append(r)
            if len(rows) >= a.n:
                break
        clips, turns, segs, cursor = [], [], [], int(0.4 * SR)
        for i, r in enumerate(rows, 1):
            wav, sr = sf.read(io.BytesIO(r["audio"]["bytes"]), dtype="float32")
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
            if sr != SR:
                wav = resample_poly(wav, SR, sr).astype(np.float32)
            spk = "S1" if int(r.get("gender", 0)) == 0 else "S2"
            clips.append((cursor, wav))
            turns.append({"id": f"t{i:03d}", "speaker": spk, "lang": lang.split("_")[0],
                          "text": r["raw_transcription"], "tts": r["transcription"]})
            segs.append({"turn_id": f"t{i:03d}", "speaker": spk, "role": "prospect",
                         "start_ms": round(cursor * 1000 / SR), "end_ms": round((cursor + len(wav)) * 1000 / SR)})
            cursor += len(wav) + int(0.5 * SR)
        mono = np.zeros(cursor + SR, np.float32)
        for st, w in clips:
            mono[st:st + len(w)] += w
        mono = mono / (np.max(np.abs(mono)) + 1e-9) * 0.9
        cd, ad = a.out / "calls" / cid, a.out / "audio" / cid
        cd.mkdir(parents=True, exist_ok=True)
        ad.mkdir(parents=True, exist_ok=True)
        (cd / "plan.json").write_text(json.dumps({"call_id": cid, "call_type": "realspeech", "language_mix": lang.split("_")[0],
                                                  "target_minutes": round(len(mono) / SR / 60, 1),
                                                  "speakers": [{"id": "S1", "role": "prospect", "name": "reader", "gender": "m"},
                                                               {"id": "S2", "role": "prospect", "name": "reader", "gender": "f"}],
                                                  "source": "google/fleurs test (CC-BY-4.0)"}, ensure_ascii=False), encoding="utf-8")
        (cd / "script.json").write_text(json.dumps({"call_id": cid, "turns": turns}, ensure_ascii=False), encoding="utf-8")
        sf.write(ad / "clean_16k.flac", mono, SR)
        # same phone degradation as the synthetic calls: band-limit, noise at 12 dB, G.711 mu-law, 8 kHz
        rng = np.random.default_rng(7)
        noise = rng.standard_normal(len(mono)).astype(np.float32)
        noise *= np.sqrt(np.mean(mono ** 2) / 10 ** 1.2 / np.mean(noise ** 2))
        x = sosfilt(butter(6, [300, 3400], btype="band", fs=SR, output="sos"), mono + noise)
        x = np.clip(x / (np.max(np.abs(x)) + 1e-9) * 0.9, -1, 1).astype(np.float32)
        with tempfile.TemporaryDirectory() as td:
            sf.write(Path(td) / "p.wav", x, SR)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{td}/p.wav", "-ar", "8000", "-ac", "1",
                            "-c:a", "pcm_mulaw", f"{td}/m.wav"], check=True)
            y, _ = sf.read(f"{td}/m.wav", dtype="float32")
        sf.write(ad / "phone_8k.flac", y, 8000)
        (ad / "segments.json").write_text(json.dumps(segs), encoding="utf-8")
        (ad / "render.json").write_text(json.dumps({"call_id": cid, "seconds": round(len(mono) / SR, 1), "snr_db": 12,
                                                    "phone_codec": "mulaw", "engines": ["fleurs-real"]}), encoding="utf-8")
        print(cid, len(rows), "utterances", round(len(mono) / SR / 60, 1), "min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

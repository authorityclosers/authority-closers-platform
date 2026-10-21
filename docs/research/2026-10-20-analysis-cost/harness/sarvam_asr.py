#!/usr/bin/env python3
"""Sarvam batch speech-to-text with diarization (saaras:v4) for the benchmark (fictional calls only).

Usage (scoring venv, keys from ac-infisical-run): sarvam_asr.py --variant phone_8k [--calls fx-01 ...]
Writes results/asr/sarvam_saaras-v4/<variant>/<call>.json in the harness segment format and a ledger row.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from common import ROOT, STT_PER_MIN, key, ledger_append

CALLS = ROOT / "bench" / "calls"
AUDIO = ROOT / "bench" / "audio"
RES = ROOT / "results"


def seconds(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="phone_8k")
    ap.add_argument("--calls", nargs="*")
    ap.add_argument("--model", default="saaras:v4")
    a = ap.parse_args()
    from sarvamai import SarvamAI

    client = SarvamAI(api_subscription_key=key("SARVAM_API_KEY"))
    ids = a.calls or [p.name for p in sorted(CALLS.iterdir()) if (p / "facts.json").exists() and not p.name.startswith("sm-")]
    arm = f"sarvam_{a.model.replace(':', '-')}"
    for cid in ids:
        out = RES / "asr" / arm / a.variant / f"{cid}.json"
        if out.exists():
            continue
        audio = AUDIO / cid / f"{a.variant}.flac"
        lang = json.loads((CALLS / cid / "plan.json").read_text(encoding="utf-8"))["language_mix"]
        code = {"mr-en": "mr-IN", "mr": "mr-IN", "hi-en": "hi-IN", "hi": "hi-IN", "en-IN": "en-IN", "gu-en": "gu-IN"}.get(lang, "unknown")
        n_spk = len(json.loads((CALLS / cid / "plan.json").read_text(encoding="utf-8"))["speakers"])
        t0 = time.time()
        status, segs, err = 200, [], None
        try:
            job = client.speech_to_text_job.create_job(model=a.model, mode="codemix" if lang.endswith("-en") and a.model == "saaras:v3" else "transcribe",
                                                       language_code=code, with_diarization=True, num_speakers=n_spk)
            job.upload_files(file_paths=[str(audio)])
            job.start()
            job.wait_until_complete(poll_interval=5, timeout=3600)
            with tempfile.TemporaryDirectory() as td:
                job.download_outputs(output_dir=td)
                files = list(Path(td).glob("*.json"))
                data = json.loads(files[0].read_text(encoding="utf-8"))
            for e in (data.get("diarized_transcript") or {}).get("entries", []):
                segs.append({"speaker": f"speaker_{e.get('speaker_id')}", "start_ms": int(float(e["start_time_seconds"]) * 1000),
                             "end_ms": int(float(e["end_time_seconds"]) * 1000), "text": e["transcript"]})
            if not segs and data.get("transcript"):
                segs = [{"speaker": "speaker_0", "start_ms": 0, "end_ms": int(seconds(audio) * 1000), "text": data["transcript"]}]
        except Exception as exc:  # recorded, never raised
            status, err = 500, f"{type(exc).__name__}: {str(exc)[:200]}"
        dt = time.time() - t0
        secs = seconds(audio)
        ledger_append({"provider": "sarvam", "model": f"sarvam/{a.model}", "tag": "stt", "call": cid, "status": status,
                       "audio_s": round(secs, 1), "list_usd": round(STT_PER_MIN["sarvam/batch-diarize"] * secs / 60, 6),
                       "billed_usd": 0.0, "latency_s": round(dt, 1), "error": err})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"status": status, "segments": segs, "error": err, "wall_s": round(dt, 1)},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(cid, arm, a.variant, status, len(segs), round(dt, 1), err or "", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

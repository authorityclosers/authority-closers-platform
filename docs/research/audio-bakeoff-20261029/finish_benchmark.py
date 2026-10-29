# ruff: noqa: E402, S310, S603
"""Sequential after the ASR runs: cached cold load, baseline and prototype proof."""

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from ac_platform.conversation_intelligence.audio_bakeoff.worker import inspect_with_local_audio
from ac_platform.conversation_intelligence.signals import inspect_media

root = Path.cwd()
if len(sys.argv) == 1:
    with Path("diar-wespeaker.jsonl").open("w") as out, Path("diar-wespeaker.err").open("w") as err:
        subprocess.run(
            [str(root / "venv/bin/python"), "benchmark.py", "diar"],
            env={**os.environ, "DIAR_EMBEDDING": "models/wespeaker.onnx"},
            stdout=out,
            stderr=err,
            check=False,
        )
# Includes child CPU and child max RSS. No model download or compilation in these timings.
for name, fn in [
    ("audioatlas", lambda p, o: inspect_media(p, o, rate=16000)),
    (
        "prototype",
        lambda p, o: inspect_with_local_audio(p, o, model_root=root / "models", enabled=True),
    ),
]:
    if len(sys.argv) > 1 and name != "audioatlas":
        continue
    p = root / "data/synthetic.wav"
    out = root / (f"proof-{name}" + ("-fresh" if len(sys.argv) > 1 else ""))
    begin = time.perf_counter()
    cpu = time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = fn(p, out)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    elapsed = time.perf_counter() - begin
    side = out / "local-audio-experiment.json"
    print(
        json.dumps(
            dict(
                engine=name,
                audio_ms=result["media_duration_ms"],
                elapsed_ms=elapsed * 1000,
                rtf=elapsed / (result["media_duration_ms"] / 1000),
                cpu_seconds_per_minute=(
                    time.process_time()
                    - cpu
                    + after.ru_utime
                    + after.ru_stime
                    - before.ru_utime
                    - before.ru_stime
                )
                / (result["media_duration_ms"] / 60000),
                parent_peak_ram_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                child_peak_ram_kib=after.ru_maxrss,
                sidecar_present=side.exists(),
                sidecar_schema=json.loads(side.read_text())["schema"] if side.exists() else None,
            )
        ),
        flush=True,
    )

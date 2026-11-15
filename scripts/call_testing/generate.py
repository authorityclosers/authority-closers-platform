"""Render the release-call library to MP3 once per library version (runs on ac).

    generate.py <out-root> --voices <piper voices dir> [--set full] [--python <venv python>]

Writes ``<out-root>/<library sha[:12]>/``: ``R01.mp3`` … and ``manifest.json`` (each file's
length, size, SHA-256, seconds of speech per side and the scenario's expectation). The audio
comes from the simulation lab's ``synth.py`` (offline piper voices, the far side band-limited
like a phone line); ``pad_to_seconds`` adds faint line noise up to that length (dead air).
Run it inside ``ac-strikes.slice`` at nice 15 (the lab's ``simlab`` wrapper); it needs ffmpeg.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent / "simulation" / "synth.py"


def _scenarios() -> Any:
    spec = importlib.util.spec_from_file_location("call_testing_scenarios", HERE / "scenarios.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["call_testing_scenarios"] = module
    spec.loader.exec_module(module)
    return module


def seconds_of(path: Path) -> float:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return round(float(out or 0), 2)


def pad(source: Path, target: Path, seconds: float) -> None:
    """Pad with faint, phone-band line noise to ``seconds`` (the call stays connected)."""
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.004:sample_rate=16000",
            "-filter_complex",
            f"[0:a]apad=whole_dur={seconds}[a];[1:a]highpass=f=300,lowpass=f=3400[n];"
            "[a][n]amix=inputs=2:duration=first:normalize=0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "32k",
            str(target),
        ],
        check=True,
    )


def speech(truth: dict[str, Any]) -> dict[str, float]:
    sides: dict[str, float] = {}
    for turn in truth.get("timeline") or []:
        sides[turn["who"]] = round(sides.get(turn["who"], 0.0) + turn["end"] - turn["start"], 1)
    return sides


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--voices", required=True)
    parser.add_argument("--set", default="full")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    scenarios = _scenarios()
    library_sha = scenarios.library_sha256()
    root = Path(args.out) / library_sha[:12]
    (root / "scenarios").mkdir(parents=True, exist_ok=True)
    manifest_file = root / "manifest.json"
    manifest = json.loads(manifest_file.read_text("utf-8")) if manifest_file.exists() else {}
    manifest.update(
        {
            "schema": "ac.call-testing.manifest/1",
            "library_version": scenarios.LIBRARY_VERSION,
            "library_sha256": library_sha,
        }
    )
    entries = manifest.setdefault("scenarios", {})
    for call in scenarios.pick(args.set):
        sid = call["id"]
        target = root / f"{sid}.mp3"
        if sid in entries and target.exists():
            print(sid, "kept", entries[sid]["seconds"], "s")
            continue
        spec_file = root / "scenarios" / f"{sid}.json"
        spec_file.write_text(json.dumps(call, ensure_ascii=False, indent=1), "utf-8")
        subprocess.run(  # noqa: S603
            [
                args.python,
                str(SYNTH),
                str(spec_file),
                str(root / "render"),
                "--voices",
                args.voices,
            ],
            check=True,
        )
        rendered = root / "render" / sid / f"{sid}.mp3"
        truth = json.loads((root / "render" / sid / "truth.json").read_text("utf-8"))
        if call.get("pad_to_seconds"):
            pad(rendered, target, float(call["pad_to_seconds"]))
        else:
            shutil.copyfile(rendered, target)
        data = target.read_bytes()
        entries[sid] = {
            "file": target.name,
            "seconds": seconds_of(target),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "speech_seconds": speech(truth),
            "title": call["title"],
            "expect": call["expect"],
        }
        print(sid, entries[sid]["seconds"], "s", entries[sid]["speech_seconds"], call["title"])
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    print("manifest", manifest_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())

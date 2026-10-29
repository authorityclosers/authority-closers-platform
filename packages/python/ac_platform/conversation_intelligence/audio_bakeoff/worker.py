"""Separate opt-in worker adapter; deliberately not registered in service composition.

Always preserves the existing C1 AudioAtlas artifact/schema. Opt-in adds a sidecar;
failures retain AudioAtlas. Nothing authorizes provider calls or transcript generation.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence.signals import (
    _FORMATS,
    SignalError,
    _run_bounded,
    file_sha256,
    inspect_media,
)


def inspect_with_local_audio(
    media: Path,
    outdir: Path,
    *,
    model_root: Path,
    enabled: bool = False,
) -> dict[str, Any]:
    result = inspect_media(media, outdir, rate=16000)
    if not enabled:
        return result
    try:
        if result["media_duration_ms"] > 600_000:
            raise SignalError("local_audio_duration_limit")
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise SignalError("local_audio_decoder_missing")
        with tempfile.TemporaryDirectory(prefix=".local-audio-", dir=outdir.parent) as folder:
            root = Path(folder)
            wav = root / "mono.wav"
            if file_sha256(media) != result["source_sha256"]:
                raise SignalError("local_audio_source_changed")
            _run_bounded(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    _FORMATS,
                    "-i",
                    str(media),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-t",
                    "601",
                    "-fs",
                    "19240000",
                    "-c:a",
                    "pcm_s16le",
                    "-n",
                    str(wav),
                ],
                timeout=90,
                watched_outputs={wav: 19_300_000},
            )
            if file_sha256(media) != result["source_sha256"]:
                raise SignalError("local_audio_source_changed")
            raw = _run_bounded(
                [
                    sys.executable,
                    "-m",
                    "ac_platform.conversation_intelligence.audio_bakeoff.worker",
                    str(wav),
                    str(model_root),
                ],
                timeout=300,
                max_stdout_bytes=2_000_000,
            )
            sidecar = json.loads(raw)
            if (
                not isinstance(sidecar, dict)
                or sidecar.get("schema") != "ac.local-audio-experiment/1"
                or sidecar.get("clock") != "decoded_audio_track"
            ):
                raise SignalError("local_audio_invalid_result")
            sidecar["source_sha256"] = result["source_sha256"]
            # A separate sidecar never impersonates the existing canonical C1 payload.
            (outdir / "local-audio-experiment.json").write_text(
                json.dumps(sidecar, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (SignalError, OSError, ValueError, KeyError):
        try:
            (outdir / "local-audio-experiment.json").unlink(missing_ok=True)
            # Constant diagnostic; optional status storage must not break canonical C1.
            (outdir / "local-audio-experiment-status.json").write_text(
                '{"status":"audioatlas_fallback"}\n', encoding="utf-8"
            )
        except OSError:
            pass
    return result


if __name__ == "__main__":
    # This helper has no downloader or provider dependency. Run in a network-denied,
    # memory-limited container before activation; time bounds are not an OS sandbox.
    from ac_platform.conversation_intelligence.audio_bakeoff.engine import analyze

    try:
        print(json.dumps(analyze(Path(sys.argv[1]), Path(sys.argv[2])), allow_nan=False))
    except Exception:
        raise SystemExit(1) from None

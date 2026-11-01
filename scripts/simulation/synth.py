"""Two-speaker call audio from a scenario, with offline TTS (piper) and real-world damage.

    synth.py <scenario.json> <out-dir> --voices <dir> [--amr-lib <libopencore-amrnb.so.0>]

Writes ``<out-dir>/<id>/``:
- ``<id>.<format>``: the file the injectors upload (Xiaomi-style AMR 8 kHz, M4A, MP3,
  WAV, or stereo M4A with the seller left and the prospect right);
- ``truth.json``: the scenario plus each turn's start and end in the recording, so the
  grader can line transcript segments up with who really spoke.

Damage, as the scenario's ``audio`` asks: the far side band-limited like a phone line,
market noise at a set SNR, crosstalk (a cut-off line overlaps the next), speakerphone echo,
one side silent, quiet or jumping levels. Runs on ac only (nice 15, ac-strikes.slice); it
needs the simlab venv (piper-tts, numpy) and ffmpeg.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import random
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np

RATE = 16000
LONG_SECONDS = 20 * 60  # longer calls render straight to disk, without effects


def _voice_loader(folder: Path) -> Any:
    from piper import PiperVoice  # type: ignore[import-not-found]

    cache: dict[str, Any] = {}

    def load(model: str) -> Any:
        if model not in cache:
            cache[model] = PiperVoice.load(str(folder / f"{model}.onnx"))
        return cache[model]

    return load


def _resample(audio: np.ndarray, source: int, target: int) -> np.ndarray:
    if source == target or audio.size == 0:
        return audio
    count = int(round(audio.size * target / source))
    positions = np.linspace(0, audio.size - 1, count)
    return np.interp(positions, np.arange(audio.size), audio).astype(np.float32)


def speak(load: Any, spec: Any, text: str, pace: float) -> np.ndarray:
    """One turn as float32 at RATE."""
    from piper import SynthesisConfig  # type: ignore[import-not-found]

    model, speaker = (spec, None) if isinstance(spec, str) else (spec["model"], spec.get("speaker"))
    voice = load(model)
    config = SynthesisConfig(speaker_id=speaker, length_scale=pace)
    parts = [chunk.audio_float_array for chunk in voice.synthesize(text, syn_config=config)]
    audio = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
    return _resample(audio.astype(np.float32), voice.config.sample_rate, RATE)


def phone_band(audio: np.ndarray) -> np.ndarray:
    """A rough 300-3400 Hz phone line (FFT mask, cheap and dependency-free)."""
    if audio.size == 0:
        return audio
    spectrum = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(audio.size, 1 / RATE)
    spectrum[(freqs < 300) | (freqs > 3400)] *= 0.05
    return np.fft.irfft(spectrum, n=audio.size).astype(np.float32)


def rms(audio: np.ndarray) -> float:
    voiced = audio[np.abs(audio) > 1e-3]
    return float(np.sqrt(np.mean(voiced**2))) if voiced.size else 0.0


def market_noise(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Pink-ish noise with slow swells and short horn-like tones."""
    count = int(seconds * RATE)
    white = rng.standard_normal(count).astype(np.float32)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(count, 1 / RATE)
    spectrum[1:] /= np.sqrt(freqs[1:])
    pink = np.fft.irfft(spectrum, n=count).astype(np.float32)
    pink /= np.max(np.abs(pink)) + 1e-9
    swell = 0.6 + 0.4 * np.sin(np.linspace(0, seconds / 3, count)).astype(np.float32)
    noise = pink * swell
    for _ in range(int(seconds / 20)):
        start = int(rng.uniform(0, max(1, count - RATE)))
        t = np.arange(int(0.4 * RATE)) / RATE
        noise[start : start + t.size] += 0.5 * np.sin(2 * np.pi * 420 * t).astype(np.float32)
    return noise


def plan(scenario: dict[str, Any], seed: int) -> tuple[list[dict[str, Any]], float]:
    """Each turn's pace and gap; crosstalk turns (no closing punctuation) overlap."""
    rng = random.Random(seed)  # noqa: S311 - pacing only, the same every run
    # Phone speech: about 130-150 words a minute (piper at 1.0 runs near 180).
    pace = {"S": rng.uniform(1.12, 1.22), "P": rng.uniform(1.15, 1.3), "I": 1.0}
    rows = []
    for index, (who, text) in enumerate(scenario["turns"]):
        cut = scenario["audio"].get("crosstalk") and not text.rstrip().endswith((".", "?", "!"))
        gap = -0.7 if cut else rng.uniform(0.5, 1.4)
        if who == "I" and index and scenario["turns"][index - 1][0] == "I":
            gap = 1.2
        rows.append({"index": index, "who": who, "text": text, "pace": pace[who], "gap": gap})
    return rows, pace["P"]


def render(scenario: dict[str, Any], voices: Path, out: Path) -> dict[str, Any]:
    load = _voice_loader(voices)
    seed = int(scenario["id"][1:]) * 7919
    rows, _ = plan(scenario, seed)
    audio_spec = scenario["audio"]
    rng = np.random.default_rng(seed)
    cursor = 0.6
    clips: list[tuple[str, int, np.ndarray]] = []
    long_call = False
    long_writer: wave.Wave_write | None = None
    raw = out / "long-mix.wav"
    for row in rows:
        clip = speak(load, scenario["voices"][row["who"]], row["text"], row["pace"])
        start = max(0.0, cursor + (row["gap"] if clips or long_writer else 0.0))
        row["start"] = round(start, 2)
        row["end"] = round(start + clip.size / RATE, 2)
        cursor = row["end"]
        if not long_call and cursor > LONG_SECONDS:
            long_call = True
            long_writer = wave.open(str(raw), "wb")  # noqa: SIM115 - closed after the last turn
            long_writer.setnchannels(1)
            long_writer.setsampwidth(2)
            long_writer.setframerate(RATE)
            written = 0
            for who, at, piece in clips:
                pad = at - written
                if pad > 0:
                    long_writer.writeframes(np.zeros(pad, dtype=np.int16).tobytes())
                    written += pad
                piece = piece[max(0, -pad) :]
                long_writer.writeframes(_pcm(piece if who == "S" else phone_band(piece)))
                written += piece.size
            clips = [("_written", written, np.zeros(0, dtype=np.float32))]
        if long_call and long_writer is not None:
            written = clips[0][1]
            at = int(start * RATE)
            pad = at - written
            if pad > 0:
                long_writer.writeframes(np.zeros(pad, dtype=np.int16).tobytes())
                written += pad
            piece = clip[max(0, -pad) :]
            long_writer.writeframes(_pcm(piece if row["who"] == "S" else phone_band(piece)))
            clips[0] = ("_written", written + piece.size, clips[0][2])
        else:
            clips.append((row["who"], int(start * RATE), clip))
    if long_writer is not None:
        long_writer.writeframes(np.zeros(int(0.8 * RATE), dtype=np.int16).tobytes())
        long_writer.close()
        source = raw
        channels = 1
    else:
        total = max(at + piece.size for _, at, piece in clips) + int(0.8 * RATE)
        sides = {"S": np.zeros(total, np.float32), "P": np.zeros(total, np.float32)}
        for who, at, piece in clips:
            side = "S" if who == "S" else "P"
            sides[side][at : at + piece.size] += piece
        sides["P"] = phone_band(sides["P"])
        levels = audio_spec.get("levels") or {}
        for side in ("S", "P"):
            gain = 10 ** (levels.get(side, 0) / 20)
            sides[side] *= gain
        if levels.get("jumps"):
            for who, at, piece in clips:
                side = "S" if who == "S" else "P"
                sides[side][at : at + piece.size] *= 10 ** (rng.uniform(-9, 6) / 20)
        if audio_spec.get("echo"):
            far = sides["P"].copy()
            for delay, decay in ((0.11, 0.45), (0.23, 0.25), (0.37, 0.12)):
                shift = int(delay * RATE)
                far[shift:] += decay * sides["P"][:-shift]
            leak = int(0.18 * RATE)
            far[leak:] += 0.3 * phone_band(sides["S"])[:-leak]
            sides["P"] = far
        if audio_spec.get("silent_side"):
            sides[audio_spec["silent_side"]][:] = 0.0
        stereo = audio_spec.get("channels") == 2
        mix = np.stack([sides["S"], sides["P"]], axis=1) if stereo else sides["S"] + sides["P"]
        if audio_spec.get("noise"):
            speech = rms(mix if not stereo else mix.mean(axis=1))
            noise = market_noise(total / RATE, rng)
            noise *= speech / (rms(noise) + 1e-9) / (10 ** (audio_spec["snr_db"] / 20))
            mix = mix + (noise[:, None] if stereo else noise)
        peak = float(np.max(np.abs(mix))) or 1.0
        mix = mix * min(1.0, 0.89 / peak)
        source = out / "mix.wav"
        channels = 2 if stereo else 1
        with wave.open(str(source), "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(RATE)
            handle.writeframes(_pcm(mix))
    return {"rows": rows, "source": source, "channels": channels}


def _pcm(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def amr_encode(wav: Path, target: Path, library: str) -> None:
    """AMR-NB 12.2 kbit/s with libopencore-amrnb through ctypes (8 kHz mono)."""
    lib = ctypes.CDLL(library)
    lib.Encoder_Interface_init.restype = ctypes.c_void_p
    lib.Encoder_Interface_init.argtypes = [ctypes.c_int]
    lib.Encoder_Interface_Encode.restype = ctypes.c_int
    lib.Encoder_Interface_Encode.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_short),
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int,
    ]
    lib.Encoder_Interface_exit.argtypes = [ctypes.c_void_p]
    pcm = subprocess.run(  # noqa: S603 - a fixed ffmpeg command on our own files
        ["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],  # noqa: S607
        check=True,
        capture_output=True,
    ).stdout
    samples = np.frombuffer(pcm, dtype="<i2")
    state = lib.Encoder_Interface_init(0)
    out = bytearray(b"#!AMR\n")
    frame = (ctypes.c_short * 160)()
    buffer = (ctypes.c_ubyte * 64)()
    try:
        for offset in range(0, samples.size - samples.size % 160, 160):
            ctypes.memmove(frame, samples[offset : offset + 160].tobytes(), 320)
            size = lib.Encoder_Interface_Encode(state, 7, frame, buffer, 0)  # MR122
            out += bytes(buffer[:size])
    finally:
        lib.Encoder_Interface_exit(state)
    target.write_bytes(bytes(out))


def encode(source: Path, target: Path, spec: dict[str, Any], channels: int, amr_lib: str) -> None:
    fmt = spec["format"]
    if fmt == "amr":
        amr_encode(source, target, amr_lib)
        return
    args = ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ac", str(channels)]
    if fmt == "m4a":
        args += [
            "-ar",
            str(spec.get("rate", 16000)),
            "-c:a",
            "aac",
            "-b:a",
            "48k" if channels == 2 else "32k",
        ]
    elif fmt == "mp3":
        args += ["-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k"]
    elif fmt == "wav":
        args += ["-ar", "16000", "-c:a", "pcm_s16le"]
    else:
        raise ValueError(fmt)
    subprocess.run([*args, str(target)], check=True)  # noqa: S603, S607


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("out")
    parser.add_argument("--voices", required=True)
    parser.add_argument("--amr-lib", default="")
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    out = Path(args.out) / scenario["id"]
    out.mkdir(parents=True, exist_ok=True)
    result = render(scenario, Path(args.voices), out)
    target = out / f"{scenario['id']}.{scenario['audio']['format']}"
    encode(result["source"], target, scenario["audio"], result["channels"], args.amr_lib)
    probe = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    truth = {
        **scenario,
        "timeline": [
            {k: row[k] for k in ("index", "who", "start", "end")} for row in result["rows"]
        ],
        "file": target.name,
        "duration_seconds": round(float(probe or 0), 2),
        "bytes": target.stat().st_size,
    }
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), "utf-8")
    result["source"].unlink(missing_ok=True)
    print(scenario["id"], target.name, truth["duration_seconds"], "s", truth["bytes"], "bytes")


if __name__ == "__main__":
    sys.exit(main())

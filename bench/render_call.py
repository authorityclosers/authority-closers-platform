#!/usr/bin/env python3
"""Render a fictional benchmark call (script.json) to audio with open TTS, on a CPU runner.

Outputs in <out>/<call_id>/:
  clean_16k.flac   mono 16 kHz mix
  stereo_16k.flac  salesperson left, everyone else right
  phone_8k.flac    300-3400 Hz band, background noise at the call's SNR, through the AMR-NB codec, 8 kHz
  segments.json    ground-truth turn timings on the mix: [{turn_id, speaker, start_ms, end_ms}]
  render.json      engines, voices, seed, SNR, durations

Engines: Kokoro-82M (Apache-2.0) for English and Hindi; Marathi and Gujarati use Indic Parler-TTS when HF_TOKEN is
set (gated, Apache-2.0), else MMS-TTS (CC-BY-NC-4.0, research only) with a per-speaker pitch shift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

SR = 16000
KOKORO_VOICES = {  # (lang_code, gender) -> voices
    ("h", "f"): ["hf_alpha", "hf_beta"],
    ("h", "m"): ["hm_omega", "hm_psi"],
    ("b", "f"): ["bf_emma", "bf_isabella"],
    ("b", "m"): ["bm_george", "bm_lewis"],
}
PARLER_SPEAKERS = {"mr": {"f": ["Sunita"], "m": ["Sanjay"]}, "gu": {"f": ["Neha"], "m": ["Yash"]},
                   "hi": {"f": ["Divya"], "m": ["Rohit"]}, "en": {"f": ["Mary"], "m": ["Thoma"]}}


def base_lang(lang: str) -> str:
    lang = (lang or "").lower()
    for code in ("mr", "gu", "hi"):
        if lang.startswith(code):
            return code
    return "en"


class Engines:
    def __init__(self, en_engine: str):
        self._kokoro: dict[str, object] = {}
        self._mms: dict[str, tuple] = {}
        self._parler = None
        self.en_engine = en_engine  # "kokoro-h" (Hindi voice reads English: Indian accent) or "kokoro-b"
        self.hf = bool(os.environ.get("HF_TOKEN"))

    def kokoro(self, code: str):
        if code not in self._kokoro:
            from kokoro import KPipeline

            self._kokoro[code] = KPipeline(lang_code=code, repo_id="hexgrad/Kokoro-82M")
        return self._kokoro[code]

    def say_kokoro(self, text: str, code: str, voice: str, speed: float) -> np.ndarray:
        parts = [np.asarray(a, dtype=np.float32) for _, _, a in self.kokoro(code)(text, voice=voice, speed=speed)]
        wav = np.concatenate(parts) if parts else np.zeros(1, np.float32)
        return resample_poly(wav, 2, 3).astype(np.float32)  # 24 kHz -> 16 kHz

    def say_mms(self, text: str, lang: str, semitones: float) -> np.ndarray:
        import torch
        from transformers import AutoTokenizer, VitsModel

        name = {"mr": "facebook/mms-tts-mar", "gu": "facebook/mms-tts-guj", "hi": "facebook/mms-tts-hin"}[lang]
        if name not in self._mms:
            self._mms[name] = (VitsModel.from_pretrained(name), AutoTokenizer.from_pretrained(name))
        model, tok = self._mms[name]
        if getattr(tok, "is_uroman", False):
            import uroman as ur

            text = ur.Uroman().romanize_string(text)
        inputs = tok(text, return_tensors="pt")
        with torch.no_grad():
            wav = model(**inputs).waveform[0].numpy().astype(np.float32)
        sr = model.config.sampling_rate
        if sr != SR:
            wav = resample_poly(wav, SR, sr).astype(np.float32)
        if semitones:
            import librosa

            wav = librosa.effects.pitch_shift(wav, sr=SR, n_steps=semitones).astype(np.float32)
        return wav

    def say_parler(self, text: str, speaker: str, style: str) -> np.ndarray:
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        if self._parler is None:
            model = ParlerTTSForConditionalGeneration.from_pretrained("ai4bharat/indic-parler-tts")
            tok = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts")
            dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
            self._parler = (model, tok, dtok)
        model, tok, dtok = self._parler
        desc = f"{speaker}'s voice is {style}, recorded close to the phone with very little background noise."
        d = dtok(desc, return_tensors="pt")
        p = tok(text, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                                 prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
        wav = out.cpu().numpy().squeeze().astype(np.float32)
        return resample_poly(wav, SR, model.config.sampling_rate).astype(np.float32)


def assign_voices(plan: dict, rng: random.Random) -> dict:
    voices = {}
    used: dict[tuple, int] = {}
    for s in plan["speakers"]:
        g = "f" if str(s.get("gender", "m")).lower().startswith("f") else "m"
        k = used.get(g, 0)
        used[g] = k + 1
        voices[s["id"]] = {
            "gender": g,
            "kokoro_h": KOKORO_VOICES[("h", g)][k % 2],
            "kokoro_b": KOKORO_VOICES[("b", g)][k % 2],
            "speed": round(rng.uniform(0.92, 1.12), 2),
            "semitones": (3.0 if g == "f" else -1.0) + (k % 2) * 1.5,
            "parler": {lang: PARLER_SPEAKERS[lang][g][0] for lang in PARLER_SPEAKERS},
            "style": rng.choice(["moderate in pace", "slightly fast", "warm and expressive", "a little monotone"]),
        }
    return voices


def synth_turn(eng: Engines, turn: dict, v: dict, call_lang: str) -> tuple[np.ndarray, str]:
    lang = base_lang(turn.get("lang") or call_lang)
    text = str(turn.get("tts") or turn.get("text"))
    if lang == "hi":
        return eng.say_kokoro(text, "h", v["kokoro_h"], v["speed"]), f"kokoro-h:{v['kokoro_h']}"
    if lang == "en":
        if eng.en_engine == "kokoro-b":
            return eng.say_kokoro(text, "b", v["kokoro_b"], v["speed"]), f"kokoro-b:{v['kokoro_b']}"
        return eng.say_kokoro(text, "h", v["kokoro_h"], v["speed"]), f"kokoro-h:{v['kokoro_h']}"
    if eng.hf:
        spk = v["parler"][lang]
        return eng.say_parler(text, spk, v["style"]), f"indic-parler:{spk}"
    return eng.say_mms(text, lang, v["semitones"]), f"mms-{lang}:{v['semitones']:+.1f}st"


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.arange(len(spec))
    spec[1:] /= np.sqrt(f[1:])
    x = np.fft.irfft(spec, n)
    return (x / (np.std(x) + 1e-9)).astype(np.float32)


def phone_version(mix: np.ndarray, snr_db: float, rng: np.random.Generator, tmp: Path) -> np.ndarray:
    sig_p = float(np.mean(mix**2)) + 1e-12
    noise = pink_noise(len(mix), rng)
    # a little hum + babble-like modulation
    t = np.arange(len(mix)) / SR
    noise = noise * (0.8 + 0.2 * np.sin(2 * np.pi * 0.3 * t)) + 0.05 * np.sin(2 * np.pi * 50 * t)
    noise *= np.sqrt(sig_p / (10 ** (snr_db / 10)) / (float(np.mean(noise**2)) + 1e-12))
    x = mix + noise
    x = sosfilt(butter(6, [300, 3400], btype="band", fs=SR, output="sos"), x)
    x = np.clip(x / (np.max(np.abs(x)) + 1e-9) * 0.9, -1, 1).astype(np.float32)
    wav = tmp / "p16.wav"
    sf.write(wav, x, SR)
    amr = tmp / "p.amr"
    out = tmp / "p8.wav"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ar", "8000", "-ac", "1",
                        "-c:a", "libopencore_amrnb", "-b:a", "12.2k", str(amr)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(amr), "-ar", "8000", str(out)], check=True)
        codec = "amr-nb-12.2k"
    except subprocess.CalledProcessError:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ar", "8000", "-ac", "1",
                        "-c:a", "pcm_mulaw", str(tmp / "p_mulaw.wav")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp / "p_mulaw.wav"),
                        "-c:a", "pcm_s16le", str(out)], check=True)
        codec = "mulaw"
    y, _ = sf.read(out, dtype="float32")
    return y, codec


def render(call_dir: Path, out_root: Path, en_engine: str) -> dict:
    plan = json.loads((call_dir / "plan.json").read_text(encoding="utf-8"))
    script = json.loads((call_dir / "script.json").read_text(encoding="utf-8"))
    cid = plan["call_id"]
    seed = int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    voices = assign_voices(plan, rng)
    roles = {s["id"]: s.get("role") for s in plan["speakers"]}
    eng = Engines(en_engine)
    clips, segs, engines_used = [], [], set()
    cursor = 0
    for t in script["turns"]:
        wav, how = synth_turn(eng, t, voices[t["speaker"]], plan.get("language_mix", "hi-en"))
        engines_used.add(how.split(":")[0])
        wav = wav / (np.max(np.abs(wav)) + 1e-9) * rng.uniform(0.45, 0.8)
        pause = int(t.get("pause_before_ms") or rng.randint(150, 700))
        overlap = int(t.get("overlap_prev_ms") or 0)
        start = max(0, cursor + int(SR * (pause - overlap) / 1000)) if segs else int(SR * 0.4)
        clips.append((start, wav, t["speaker"]))
        end = start + len(wav)
        segs.append({"turn_id": t["id"], "speaker": t["speaker"], "role": roles.get(t["speaker"]),
                     "start_ms": round(start * 1000 / SR), "end_ms": round(end * 1000 / SR)})
        cursor = max(cursor, end)
    total = cursor + int(SR * 0.6)
    mono = np.zeros(total, np.float32)
    stereo = np.zeros((total, 2), np.float32)
    for start, wav, spk in clips:
        mono[start:start + len(wav)] += wav
        ch = 0 if roles.get(spk) == "salesperson" else 1
        stereo[start:start + len(wav), ch] += wav
    peak = max(np.max(np.abs(mono)), 1e-9)
    mono = mono / peak * 0.9
    stereo = stereo / max(np.max(np.abs(stereo)), 1e-9) * 0.9
    snr = float(plan.get("phone_snr_db") or rng.choice([20, 15, 12, 10, 8]))
    out = out_root / cid
    out.mkdir(parents=True, exist_ok=True)
    sf.write(out / "clean_16k.flac", mono, SR)
    sf.write(out / "stereo_16k.flac", stereo, SR)
    with tempfile.TemporaryDirectory() as td:
        phone, codec = phone_version(mono, snr, nrng, Path(td))
    sf.write(out / "phone_8k.flac", phone, 8000)
    (out / "segments.json").write_text(json.dumps(segs, ensure_ascii=False, indent=0), encoding="utf-8")
    meta = {"call_id": cid, "seed": seed, "seconds": round(total / SR, 1), "snr_db": snr, "phone_codec": codec,
            "engines": sorted(engines_used), "en_engine": en_engine, "voices": voices}
    (out / "render.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("calls", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("audio"))
    ap.add_argument("--en-engine", default="kokoro-h", choices=["kokoro-h", "kokoro-b"])
    a = ap.parse_args()
    for c in a.calls:
        meta = render(c, a.out, a.en_engine)
        print(json.dumps({k: meta[k] for k in ("call_id", "seconds", "snr_db", "phone_codec", "engines")}))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

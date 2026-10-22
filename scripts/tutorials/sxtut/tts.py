"""ElevenLabs voice for tutorial lines, with character timings and a speech-to-text check.

The key comes from ELEVENLABS_API_KEY at run time (injected from Infisical; README "Voice"). It is
never printed, logged or written. Every line is cached by a hash of everything that shapes the
audio, so re-running a tutorial after a UI change re-records nothing that did not change and
spends no characters twice.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

API = "https://api.elevenlabs.io"


class TtsError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise TtsError(
            "ELEVENLABS_API_KEY is not set; run through scripts/tutorials/with-elevenlabs"
        )
    return key


def _request(
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> bytes:
    h = {"xi-api-key": _key(), **(headers or {})}
    # Always the fixed https://api.elevenlabs.io base; no caller-supplied scheme reaches urlopen.
    req = urllib.request.Request(API + path, data=body, headers=h, method=method)  # noqa: S310
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 + attempt * 4)
                continue
            raise TtsError(
                f"ElevenLabs {method} {path.split('?')[0]} -> {e.code}: {detail}"
            ) from None
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2 + attempt * 4)
                continue
            raise TtsError(f"ElevenLabs unreachable: {e.reason}") from None
    raise TtsError("unreachable")


def quota() -> dict:
    """Plan tier and characters left this cycle (nothing secret)."""
    sub = json.loads(_request("GET", "/v1/user/subscription"))
    return {
        "tier": sub.get("tier"),
        "used": sub.get("character_count"),
        "limit": sub.get("character_limit"),
        "left": (sub.get("character_limit") or 0) - (sub.get("character_count") or 0),
        "resets_unix": sub.get("next_character_count_reset_unix"),
    }


@dataclass(frozen=True)
class Line:
    text: str  # exactly what the voice reads (after textprep.spoken)
    lang: str  # en | hi | mr
    language_code: str
    voice_id: str
    model_id: str
    output_format: str
    voice_settings: tuple[tuple[str, float], ...]
    seed: int = 7

    def key(self) -> str:
        blob = json.dumps(
            [
                self.text,
                self.language_code,
                self.voice_id,
                self.model_id,
                self.output_format,
                list(self.voice_settings),
                self.seed,
            ],
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def line_from_cast(text: str, lang: str, cast: dict, voice: str = "pick") -> Line:
    language = cast["languages"][lang]
    return Line(
        text=text,
        lang=lang,
        language_code=language["language_code"],
        voice_id=language[voice]["voice_id"],
        model_id=cast["model_id"],
        output_format=cast["output_format"],
        voice_settings=tuple(sorted((k, float(v)) for k, v in cast["voice_settings"].items())),
    )


def synthesize(line: Line, cache: Path) -> tuple[Path, dict]:
    """Audio file and its character alignment, from cache when this exact line was made before."""
    cache.mkdir(parents=True, exist_ok=True)
    k = line.key()
    audio = cache / f"{k}.mp3"
    meta = cache / f"{k}.json"
    if audio.exists() and meta.exists():
        return audio, json.loads(meta.read_text(encoding="utf-8"))
    body = {
        "text": line.text,
        "model_id": line.model_id,
        "language_code": line.language_code,
        "voice_settings": dict(line.voice_settings),
        "seed": line.seed,
        "apply_text_normalization": "auto",
    }
    raw = _request(
        "POST",
        f"/v1/text-to-speech/{line.voice_id}/with-timestamps?output_format={line.output_format}",
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
        {"Content-Type": "application/json", "Accept": "application/json"},
    )
    data = json.loads(raw)
    tmp = audio.with_suffix(".part")
    tmp.write_bytes(base64.b64decode(data["audio_base64"]))
    tmp.replace(audio)
    info = {
        "text": line.text,
        "lang": line.lang,
        "voice_id": line.voice_id,
        "model_id": line.model_id,
        "chars": len(line.text),
        "alignment": data.get("alignment") or data.get("normalized_alignment"),
    }
    meta.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return audio, info


def transcribe(audio: Path, language_code: str | None = None) -> dict:
    """ElevenLabs Scribe transcript of a rendered line, to check product names are heard right."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        parts.append(f"--{boundary}\r\n{disposition}\r\n\r\n{value}\r\n".encode())

    field("model_id", "scribe_v1")
    if language_code:
        field("language_code", language_code)
    field("tag_audio_events", "false")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n".encode()
    )
    parts.append(audio.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    raw = _request(
        "POST",
        "/v1/speech-to-text",
        b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=300,
    )
    return json.loads(raw)


def _squash(text: str) -> str:
    # Scribe writes "Sales X-Ray" as "SalesXRay" or "Sales Xray": compare without case, spaces or
    # hyphens.
    return "".join(ch for ch in text.lower() if ch not in " -‐‑")


def heard(transcript: str, pronounce: dict) -> dict[str, bool]:
    """Which product terms the transcript contains, by their listen_for spellings."""
    t = _squash(transcript)
    return {
        term: any(_squash(s) in t for s in rule.get("listen_for", [term]))
        for term, rule in pronounce["terms"].items()
    }

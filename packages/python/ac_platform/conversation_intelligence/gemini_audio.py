"""C2 transcription on Gemini 3.1 Flash-Lite: the request, the audio and the transcript.

Owner, 21 Oct 2026 ("So at least get this on prod now!!!"): production's one-pass saving
is its transcription. Gemini 3.1 Flash-Lite tied the best Indian-language speech-to-text
on real Hindi and Marathi (cost research, 20 Oct 2026) at about a third of Scribe's
list price, and the one-pass trial ran it on real calls on development.

Pure helpers; the bounded transport (``providers.BoundedProviders``) does the network:

- ``speech_mp3``: the source as mono 16 kHz 32 kbps MP3 (bounded ffmpeg, no shell), the
  shape the research measured; it also keeps an hour of speech under the inline limit;
- ``plan_parts`` / ``cut``: a call longer than 15 minutes goes as 10-minute parts heard 30
  seconds into each other, sent at once (the broker allows 180 seconds for the whole call);
- ``request_body``: the research's prompt and strict schema (speaker, start, end, text);
- ``gemini_audio_transcript``: the answer as today's C2 transcript contract. Times come
  back as MM:SS and are normalised: ordered, at least 300 ms, inside the call; speakers
  (A, B, ...) become ``speaker_0``, ``speaker_1`` in order of first speech. Parts are
  joined on the call's clock, each overlap cut at its middle, and a part's voices are
  matched to the previous part's from the turns both heard. The revision is the provider
  response's own digest (all parts' responses together), as for Scribe and Deepgram.

Nothing here logs audio, prompts or transcript text.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.providers import ProviderResult

MODEL: Final = "gemini-3.1-flash-lite"
MODELS: Final = frozenset({MODEL})
OPERATION: Final = "transcribe_gemini_audio"
RECIPE: Final = "gemini-3.1-flash-lite-audio-v1"
PROMPT_REVISION: Final = "gemini-audio-transcript/1"
TIMEBASE: Final = "gemini-audio-mmss-v1"
MIN_SEGMENT_MS: Final = 300
MS_PER_WORD: Final = 400  # when a segment comes back without a usable end
# Real calls write 500-1,330 output tokens a minute (dev trial, 21 Oct 2026); a request
# answers up to 60,000 (Flash-Lite's own limit is 65,536), so long calls go in parts.
MAX_OUTPUT_TOKENS: Final = 60_000
SINGLE_MAX_MS: Final = 15 * 60_000
PART_MS: Final = 10 * 60_000
OVERLAP_MS: Final = 30_000
MAX_PARTS: Final = 14
BYTES_PER_SECOND: Final = 4_000  # 32 kbps
PARALLEL: Final = 8
PARTS_SCHEMA: Final = "ac.sales-xray.gemini-audio-parts/1"
# base64 grows a third; a request stays under Gemini's 20 MB inline limit.
INLINE_AUDIO_BYTES: Final = 14 * 1024 * 1024
# Inside the broker's hard 180-second limit for the whole provider call.
DEADLINE_SECONDS: Final = 170
TRANSCODE_SECONDS: Final = 300
MAX_SEGMENTS: Final = 5_000
URL: Final = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
UPLOAD_URL: Final = "https://generativelanguage.googleapis.com/upload/v1beta/files"
FILES_URL: Final = "https://generativelanguage.googleapis.com/v1beta/"

PROMPT: Final = """Transcribe this recorded phone call verbatim, every word, from start to end.
- Speakers: label them A, B, C… consistently by voice (the first voice heard is A).
- Language: write exactly what is said. Hindi and Marathi in Devanagari script; English words (including English
  words inside Hindi/Marathi sentences) in Latin script. Do not translate, correct, summarise or skip anything.
- Numbers: write amounts, dates and times as digits when spoken as numbers ("12.5 lakh", "27 October", "2:30").
- One segment per speaker turn; split a turn longer than ~30 seconds. start and end are MM:SS from the start.
- If something is inaudible write [inaudible]; never guess words."""  # noqa: E501 - the measured prompt

_S: Final = {"type": "string"}
SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"speaker": _S, "start": _S, "end": _S, "text": _S},
                "required": ["speaker", "start", "end", "text"],
            },
        }
    },
    "required": ["segments"],
}
_CLOCK = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\s*$")


class GeminiAudioError(ValueError):
    """A stable, content-free code."""


def speech_mp3(source: bytes, *, ffmpeg: str | None = None) -> bytes:
    """Mono 16 kHz 32 kbps MP3 of any input the C1 audio check accepted."""
    tool = ffmpeg or shutil.which("ffmpeg")
    if not tool:
        raise GeminiAudioError("gemini_audio_transcoder_unavailable")
    with tempfile.TemporaryDirectory(prefix="ac-c2-gemini-") as folder:
        source_path = Path(folder) / "source"
        target = Path(folder) / "call.mp3"
        source_path.write_bytes(source)
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell, private temporary files
                [
                    tool,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-b:a",
                    "32k",
                    "-f",
                    "mp3",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=TRANSCODE_SECONDS,
                env={"PATH": "/usr/bin:/bin"},
            )
            audio = target.read_bytes()
        except (subprocess.SubprocessError, OSError):
            raise GeminiAudioError("gemini_audio_transcode_failed") from None
    if not audio:
        raise GeminiAudioError("gemini_audio_transcode_failed")
    return audio


def plan_parts(total_ms: int) -> list[tuple[int, int]]:
    """(offset_ms, length_ms) of each request. A call up to 15 minutes is one request;
    a longer one is 10-minute parts, each heard 30 seconds into the next, so every part
    answers well inside the broker's 180-second limit and the output cap, and they run
    at once."""
    if total_ms <= SINGLE_MAX_MS:
        return [(0, total_ms)]
    parts: list[tuple[int, int]] = []
    offset = 0
    while offset < total_ms:
        parts.append((offset, min(PART_MS + OVERLAP_MS, total_ms - offset)))
        offset += PART_MS
        if total_ms - offset <= OVERLAP_MS:
            break  # the last part already heard the rest
    if len(parts) > MAX_PARTS:
        raise GeminiAudioError("gemini_audio_too_long")
    return parts


def speech_ms(speech: bytes) -> int:
    """The speech MP3's length from its constant 32 kbps rate."""
    return round(len(speech) * 1000 / BYTES_PER_SECOND)


def cut(speech: bytes, offset_ms: int, length_ms: int, *, ffmpeg: str | None = None) -> bytes:
    """One part of the speech MP3, copied frame by frame (no second encode)."""
    tool = ffmpeg or shutil.which("ffmpeg")
    if not tool:
        raise GeminiAudioError("gemini_audio_transcoder_unavailable")
    with tempfile.TemporaryDirectory(prefix="ac-c2-gemini-") as folder:
        source = Path(folder) / "call.mp3"
        target = Path(folder) / "part.mp3"
        source.write_bytes(speech)
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell, private temporary files
                [
                    tool,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{offset_ms / 1000:.3f}",
                    "-t",
                    f"{length_ms / 1000:.3f}",
                    "-i",
                    str(source),
                    "-c",
                    "copy",
                    "-f",
                    "mp3",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=TRANSCODE_SECONDS,
                env={"PATH": "/usr/bin:/bin"},
            )
            part = target.read_bytes()
        except (subprocess.SubprocessError, OSError):
            raise GeminiAudioError("gemini_audio_transcode_failed") from None
    if not part:
        raise GeminiAudioError("gemini_audio_transcode_failed")
    return part


def audio_part(audio: bytes, *, file_uri: str | None = None) -> dict[str, Any]:
    if file_uri is not None:
        return {"file_data": {"mime_type": "audio/mpeg", "file_uri": file_uri}}
    return {
        "inline_data": {"mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode("ascii")}
    }


def request_body(part: Mapping[str, Any]) -> dict[str, Any]:
    """The research's prompt with its strict schema; temperature 0, thinking low."""
    return {
        "systemInstruction": {"parts": [{"text": PROMPT}]},
        "contents": [
            {"role": "user", "parts": [dict(part), {"text": "Transcribe the call above."}]}
        ],
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "responseJsonSchema": SCHEMA,
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
        },
    }


def clock_ms(value: Any) -> int | None:
    """'MM:SS', 'MM:SS.s' or 'H:MM:SS' as milliseconds; None when unreadable."""
    if not isinstance(value, str):
        return None
    match = _CLOCK.match(value)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    total = (int(hours or 0) * 60 + int(minutes)) * 60 + float(seconds)
    return round(total * 1000)


def answer_of(response: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON answer inside a generateContent response (thoughts left out)."""
    try:
        candidate = response["candidates"][0]
        finish = candidate.get("finishReason")
        text = "".join(
            part.get("text", "")
            for part in candidate["content"]["parts"]
            if isinstance(part, Mapping) and not part.get("thought")
        )
    except (KeyError, IndexError, TypeError, AttributeError):
        raise GeminiAudioError("gemini_audio_response_invalid") from None
    if finish == "MAX_TOKENS":
        raise GeminiAudioError("gemini_audio_answer_too_long")
    try:
        value = json.loads(text)
    except ValueError:
        raise GeminiAudioError("gemini_audio_answer_unreadable") from None
    if not isinstance(value, dict):
        raise GeminiAudioError("gemini_audio_answer_unreadable")
    return value


def _rows(answer: Mapping[str, Any], *, offset_ms: int = 0) -> list[dict[str, Any]]:
    """One answer's readable turns: provider label, call-relative times, text."""
    raw = answer.get("segments")
    if not isinstance(raw, list) or len(raw) > MAX_SEGMENTS:
        raise GeminiAudioError("gemini_audio_segments_invalid")
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        text = " ".join(str(item.get("text") or "").split())
        start = clock_ms(item.get("start"))
        if not text or start is None:
            continue
        end = clock_ms(item.get("end"))
        rows.append(
            {
                "label": " ".join(str(item.get("speaker") or "?").split())[:32] or "?",
                "start_ms": start + offset_ms,
                "end_ms": None if end is None else end + offset_ms,
                "text": text,
            }
        )
    rows.sort(key=lambda row: row["start_ms"])
    return rows


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.casefold()) if len(word) > 1}


def _speaker_map(
    before: list[dict[str, Any]], after: list[dict[str, Any]], window: tuple[int, int]
) -> dict[str, str]:
    """The next part's labels as the previous part's speakers, from the turns both parts
    heard in their overlap (same words at about the same time); one to one, best first."""
    low, high = window
    heard = [row for row in before if low <= row["start_ms"] <= high]
    votes: dict[tuple[str, str], int] = {}
    for row in after:
        if not low <= row["start_ms"] <= high:
            continue
        words = _words(row["text"])
        best, score = None, 0.0
        for other in heard:
            union = words | _words(other["text"])
            similar = len(words & _words(other["text"])) / len(union) if union else 0.0
            if similar > score and abs(other["start_ms"] - row["start_ms"]) <= 10_000:
                best, score = other, similar
        if best is not None and score >= 0.3:
            key = (row["label"], best["speaker"])
            votes[key] = votes.get(key, 0) + 1
    mapping: dict[str, str] = {}
    for (label, speaker), _count in sorted(votes.items(), key=lambda item: -item[1]):
        if label not in mapping and speaker not in mapping.values():
            mapping[label] = speaker
    return mapping


def stitched_rows(parts: list[tuple[int, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Every part's turns on the call's own clock, each overlap cut at its middle, with
    one speaker identity across parts (``speaker`` keys, not yet numbered)."""
    rows: list[dict[str, Any]] = []
    previous: list[dict[str, Any]] = []
    for index, (offset, answer) in enumerate(parts):
        current = _rows(answer, offset_ms=offset)
        if index == 0:
            for row in current:
                row["speaker"] = f"0:{row['label']}"
        else:
            window = (offset, offset + OVERLAP_MS)
            mapping = _speaker_map(previous, current, window)
            # Voices the overlap did not settle take the call's other known speakers, in
            # order of first speech (a phone call is almost always the same two voices);
            # only more voices than that are new speakers.
            known = list(dict.fromkeys(row["speaker"] for row in rows))
            spare = [key for key in known if key not in mapping.values()]
            unsettled = [
                label
                for label in dict.fromkeys(row["label"] for row in current)
                if label not in mapping
            ]
            if len(unsettled) <= len(spare):
                mapping.update(zip(unsettled, spare, strict=False))
            for row in current:
                row["speaker"] = mapping.get(row["label"], f"{index}:{row['label']}")
            cut = offset + OVERLAP_MS // 2
            rows = [row for row in rows if row["start_ms"] < cut]
            current = [row for row in current if row["start_ms"] >= cut]
        rows.extend(current)
        # This part's turns, for matching the next part's voices in their overlap.
        previous = [row for row in rows if row["start_ms"] >= offset]
    rows.sort(key=lambda row: row["start_ms"])
    return rows


def normalized_segments(
    answer: Mapping[str, Any] | None = None,
    *,
    duration_ms: int,
    rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Ordered C2 segments and whether speech overlapped."""
    if rows is None:
        rows = _rows(answer or {})
        for row in rows:
            row["speaker"] = row["label"]
    # Speakers in order of first speech, like the other providers' labels.
    speakers: dict[str, str] = {}
    for row in rows:
        row["speaker_id"] = speakers.setdefault(row["speaker"], f"speaker_{len(speakers)}")
    segments: list[dict[str, Any]] = []
    furthest = 0
    overlap = False
    for index, row in enumerate(rows):
        start = row["start_ms"]
        if start >= duration_ms:
            continue
        end = row["end_ms"]
        following = rows[index + 1]["start_ms"] if index + 1 < len(rows) else None
        if end is None or end <= start:
            guess = start + max(MIN_SEGMENT_MS, MS_PER_WORD * len(row["text"].split()))
            end = min(guess, following) if following and following > start else guess
        end = min(max(end, start + MIN_SEGMENT_MS), duration_ms)
        if end <= start:
            start = max(0, end - MIN_SEGMENT_MS)
        overlap = overlap or start < furthest
        furthest = max(furthest, end)
        segments.append(
            {
                "id": f"s{len(segments) + 1}",
                "speaker_id": row["speaker_id"],
                "start_ms": start,
                "end_ms": end,
                "text": row["text"],
            }
        )
    if not segments:
        raise GeminiAudioError("gemini_audio_transcript_empty")
    return segments, overlap


def gemini_audio_transcript(
    result: ProviderResult, *, duration_ms: int, source_sha256: str
) -> dict[str, Any]:
    """Today's C2 transcript contract from a Gemini audio response."""
    from ac_platform.conversation_intelligence.providers import ProviderError

    if (
        result.provider != "gemini"
        or result.model not in MODELS
        or result.input_sha256 != source_sha256
        or type(duration_ms) is not int
        or duration_ms <= 0
    ):
        raise ProviderError("gemini_audio_transcript_invalid")
    try:
        if result.data.get("schema") == PARTS_SCHEMA:
            parts = result.data.get("parts")
            if not isinstance(parts, list) or not 1 < len(parts) <= MAX_PARTS:
                raise GeminiAudioError("gemini_audio_parts_invalid")
            rows = stitched_rows(
                [
                    (int(part["offset_ms"]), answer_of(part["response"]))
                    for part in parts
                    if isinstance(part, Mapping)
                ]
            )
            segments, overlap = normalized_segments(duration_ms=duration_ms, rows=rows)
        else:
            segments, overlap = normalized_segments(answer_of(result.data), duration_ms=duration_ms)
    except (GeminiAudioError, KeyError, TypeError, ValueError) as error:
        code = str(error) if isinstance(error, GeminiAudioError) else "gemini_audio_parts_invalid"
        raise ProviderError(code) from None
    return {
        "source_sha256": source_sha256,
        "revision": result.response_sha256,
        "raw_text": " ".join(segment["text"] for segment in segments),
        "raw_response_sha256": result.response_sha256,
        "timebase_id": TIMEBASE,
        "alignment_to_audioatlas": "unverified",
        "speaker_identity": "unverified_provider_labels",
        "overlap_observed": overlap,
        "segments": segments,
    }

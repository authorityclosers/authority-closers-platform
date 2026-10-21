"""Stage 1: the call's audio becomes a transcript on Gemini 3.1 Flash-Lite.

The answer is turned into today's C2 transcript contract (``source_sha256``,
``revision``, ``timebase_id``, speaker-labelled ``segments`` with ``id``,
``speaker_id``, ``start_ms``, ``end_ms`` and ``text``), checked by the Report's own
transcript validator, so alignment, the Report and the call map can read it unchanged.

The prompt and schema are the cost research's (20 Oct 2026: Flash-Lite tied the best
Indian-language speech-to-text on real Hindi and Marathi). The model writes times as
MM:SS; they are normalised here: ordered, every segment at least 300 ms long, inside
the call's duration. Speakers are labelled by voice (A, B, ...) and renamed speaker_0,
speaker_1, ... in order of first speech, like the Scribe transcripts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Final

from ac_platform.conversation_intelligence.reports import ReportError, _validated_transcript
from ac_platform.one_pass.gemini import OnePassFailure, Request

PROMPT_REVISION: Final = "one-pass-transcript/1"
TIMEBASE: Final = "gemini-audio-mmss-v1"
MIN_SEGMENT_MS: Final = 300
MS_PER_WORD: Final = 400  # when a segment comes back without a usable end
# A one-hour call writes about 27,000 tokens; Flash-Lite answers up to 65,536.
MAX_OUTPUT_TOKENS: Final = 60_000

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


def request(audio: bytes, mime: str, duration_ms: int | None) -> Request:
    return Request(
        system=PROMPT,
        user="Transcribe the call above.",
        schema=SCHEMA,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.0,
        audio=audio,
        audio_mime=mime,
        audio_seconds=(duration_ms / 1000) if duration_ms else None,
    )


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


def to_transcript(
    answer: Mapping[str, Any],
    *,
    source_sha256: str,
    duration_ms: int | None,
    response_sha256: str,
    model: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    """The C2-shaped transcript and counts of what was dropped (no content)."""
    dropped: dict[str, int] = {}

    def drop(code: str) -> None:
        dropped[code] = dropped.get(code, 0) + 1

    raw = answer.get("segments")
    if not isinstance(raw, list):
        raise OnePassFailure("transcript_missing")
    speakers: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            drop("shape")
            continue
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            drop("empty")
            continue
        start = clock_ms(item.get("start"))
        if start is None:
            drop("time")
            continue
        label = " ".join(str(item.get("speaker") or "?").split())[:32] or "?"
        speaker = speakers.setdefault(label, f"speaker_{len(speakers)}")
        rows.append(
            {
                "speaker_id": speaker,
                "start_ms": start,
                "end_ms": clock_ms(item.get("end")),
                "text": text,
            }
        )
    rows.sort(key=lambda row: row["start_ms"])
    limit = duration_ms if duration_ms and duration_ms > 0 else None
    segments: list[dict[str, Any]] = []
    furthest = 0
    overlap = False
    for index, row in enumerate(rows):
        start = row["start_ms"]
        if limit is not None and start >= limit:
            drop("after_end")
            continue
        end = row["end_ms"]
        following = rows[index + 1]["start_ms"] if index + 1 < len(rows) else None
        if end is None or end <= start:
            guess = start + max(MIN_SEGMENT_MS, MS_PER_WORD * len(row["text"].split()))
            end = min(guess, following) if following and following > start else guess
        end = max(end, start + MIN_SEGMENT_MS)
        if limit is not None:
            end = min(end, limit)
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
        raise OnePassFailure("transcript_empty")
    body = json.dumps(segments, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    revision = hashlib.sha256(f"{model}|{PROMPT_REVISION}|{body}".encode()).hexdigest()
    transcript = {
        "source_sha256": source_sha256,
        "revision": revision,
        "raw_text": " ".join(segment["text"] for segment in segments),
        "raw_response_sha256": response_sha256,
        "timebase_id": TIMEBASE,
        "alignment_to_audioatlas": "unverified",
        "speaker_identity": "unverified_provider_labels",
        "overlap_observed": overlap,
        "duration_ms": max(limit or 0, furthest),
        "segments": segments,
        "provider": {"model": model, "prompt_revision": PROMPT_REVISION},
    }
    try:
        _validated_transcript(transcript)
    except ReportError as error:
        raise OnePassFailure(f"transcript_{error}") from None
    return transcript, dropped

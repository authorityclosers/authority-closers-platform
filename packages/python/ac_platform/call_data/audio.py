"""Measured voice features per call, on the server, with no model (deep pipeline, v0.64).

The audio check (C1, AudioAtlas) already stores 10 ms frames (loudness, pitch
and spectrum) and a decimated waveform. Here they are joined with the
transcript's segments: per speaker and per segment loudness, pitch and pace,
plus talk ratio, pauses and overlap. Pure: rows come in, numbers come out.
Physical channels are not speakers; the transcript's speaker labels are.
"""

from __future__ import annotations

import math
import statistics
import struct
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from ac_platform.call_data.extraction import Segment

PEAK_POINTS = 200
PAUSE_MS = 1500
LONG_PAUSE_MS = 3000
_HEADER = struct.Struct("<8sIIQIIQ")
_ROW = struct.Struct("<IBHHB14f")
_MAGIC = b"ACAAF001"
_DBFS, _F0, _PERIODICITY = 1, 12, 13  # descriptor positions (signals.FEATURE_COLUMNS)
_PITCH_MISSING = 4


class AudioError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def frames(blob: bytes) -> tuple[int, Iterator[tuple[float, float, float]]]:
    """(rate, frames of (time_ms, dbfs, f0 or nan)) from an AudioAtlas feature file, channel 0."""
    if len(blob) < _HEADER.size:
        raise AudioError("features_short")
    magic, rate, channels, _samples, _window, _hop, rows = _HEADER.unpack_from(blob, 0)
    if magic != _MAGIC or rate <= 0 or channels <= 0:
        raise AudioError("features_header")
    if len(blob) != _HEADER.size + rows * _ROW.size:
        raise AudioError("features_size")

    def iterate() -> Iterator[tuple[float, float, float]]:
        for offset in range(_HEADER.size, len(blob), _ROW.size):
            start, channel, _valid, _invalid, flags, *values = _ROW.unpack_from(blob, offset)
            if channel != 0:
                continue
            f0 = values[_F0]
            pitched = (
                not flags & _PITCH_MISSING
                and math.isfinite(f0)
                and f0 > 0
                and values[_PERIODICITY] >= 0.5
            )
            yield start / rate * 1000, values[_DBFS], f0 if pitched else math.nan

    return rate, iterate()


def peaks(display_dbfs: Sequence[float], points: int = PEAK_POINTS) -> list[float]:
    """The waveform as 0..1 heights (-60 dBFS and quieter is 0), at most ``points`` long."""
    values = [v for v in display_dbfs if isinstance(v, (int, float)) and math.isfinite(v)]
    if not values:
        return []
    step = max(1, math.ceil(len(values) / points))
    result = []
    for index in range(0, len(values), step):
        loudest = max(values[index : index + step])
        result.append(round(min(1.0, max(0.0, (loudest + 60) / 60)), 3))
    return result


def _words(text: str) -> int:
    return len(text.split())


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _mean_db(values: list[float]) -> float | None:
    usable = [v for v in values if math.isfinite(v) and v > -120]
    if not usable:
        return None
    # Mean in the power domain, not of the decibel numbers.
    power = sum(10 ** (v / 10) for v in usable) / len(usable)
    return round(10 * math.log10(power), 1)


def features(
    segments: Sequence[Segment],
    *,
    roles: Mapping[str, str],
    duration_ms: int,
    display_dbfs: Sequence[float] = (),
    frame_rows: Iterable[tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    """The audio.features value: waveform, loudness, pitch, pace, pauses, overlap."""
    ordered = sorted(segments, key=lambda s: (s.start_ms, s.end_ms))
    per_segment_db: dict[str, list[float]] = {s.id: [] for s in ordered}
    per_segment_f0: dict[str, list[float]] = {s.id: [] for s in ordered}
    if frame_rows is not None:
        index = 0
        for time_ms, dbfs, f0 in frame_rows:
            while index < len(ordered) and ordered[index].end_ms <= time_ms:
                index += 1
            if index >= len(ordered):
                break
            segment = ordered[index]
            if segment.start_ms <= time_ms < segment.end_ms:
                per_segment_db[segment.id].append(dbfs)
                if math.isfinite(f0):
                    per_segment_f0[segment.id].append(f0)

    speakers: dict[str, dict[str, Any]] = {}
    totals: dict[str, dict[str, Any]] = {}
    segment_rows = []
    for segment in ordered:
        label = roles.get(segment.speaker, segment.speaker)
        span = max(1, segment.end_ms - segment.start_ms)
        words = _words(segment.text)
        bucket = totals.setdefault(label, {"talk_ms": 0, "words": 0, "db": [], "f0": []})
        bucket["talk_ms"] += span
        bucket["words"] += words
        bucket["db"].extend(per_segment_db[segment.id])
        bucket["f0"].extend(per_segment_f0[segment.id])
        segment_rows.append(
            {
                "segment_id": segment.id,
                "loudness_dbfs": _mean_db(per_segment_db[segment.id]),
                "pitch_hz": _median(per_segment_f0[segment.id]),
                "pace_wpm": round(words / (span / 60000), 1) if span >= 1000 else None,
            }
        )
    talk_total = sum(b["talk_ms"] for b in totals.values()) or 1
    for label, bucket in totals.items():
        minutes = bucket["talk_ms"] / 60000
        speakers[label] = {
            "talk_ms": bucket["talk_ms"],
            "share": round(bucket["talk_ms"] / talk_total, 4),
            "words": bucket["words"],
            "pace_wpm": round(bucket["words"] / minutes, 1) if minutes > 0 else None,
            "loudness_dbfs": _mean_db(bucket["db"]),
            "pitch_hz": _median(bucket["f0"]),
        }

    gaps, overlap = [], 0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        gap = current.start_ms - previous.end_ms
        if gap >= PAUSE_MS:
            gaps.append(gap)
        elif gap < 0 and current.speaker != previous.speaker:
            overlap += min(-gap, current.end_ms - current.start_ms)
    all_db = [v for values in per_segment_db.values() for v in values]
    all_f0 = [v for values in per_segment_f0.values() for v in values]
    result: dict[str, Any] = {
        "duration_ms": int(duration_ms),
        "peaks": peaks(display_dbfs),
        "speakers": speakers,
        "pauses": {
            "count": len(gaps),
            "long": sum(1 for gap in gaps if gap >= LONG_PAUSE_MS),
            "total_ms": sum(gaps),
            "longest_ms": max(gaps, default=0),
        },
        "overlap_ms": overlap,
        "segments": segment_rows,
        "source": "audioatlas frames" if frame_rows is not None else "transcript timings only",
    }
    loudness, pitch = _mean_db(all_db), _median(all_f0)
    if loudness is not None:
        result["loudness_dbfs"] = loudness
    if pitch is not None:
        result["pitch_hz"] = pitch
    return result


def talk_ratio(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """The conversation.talk_ratio value from the audio features (shares sum to 1)."""
    parts = {
        str(label): float(part["share"])
        for label, part in value["speakers"].items()
        if isinstance(part, dict) and isinstance(part.get("share"), (int, float))
    }
    if not parts:
        return None
    total = sum(parts.values()) or 1
    return {"parts": {label: round(share / total, 4) for label, share in parts.items()}}

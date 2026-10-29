"""Offline ONNX VAD/anonymous speaker turns. Optional AWS-tested dependencies only.

No ASR, scoring, role inference, downloads, or provider calls. The caller must supply
16 kHz mono PCM WAV. Speaker clusters are not seller/prospect identities.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence.signals import SignalError, file_sha256

ARTIFACTS = {
    "embedding.onnx": "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
    "segmentation.int8.onnx": "d582f4b4c6b48205de7e0643c57df0df5615a3c176189be3fc461e9d18827b5d",
    "silero.onnx": "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
}
MAX_SECONDS = 600


def verify_artifacts(root: Path) -> None:
    for name, digest in ARTIFACTS.items():
        path = root / name
        if not path.is_file() or path.is_symlink() or file_sha256(path) != digest:
            raise SignalError("local_audio_artifact_mismatch")


def _union(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def summarize(turns: list[dict[str, Any]], duration_ms: float) -> dict[str, Any]:
    """Union same-speaker regions before computing overlap-inclusive talk shares."""
    if not math.isfinite(duration_ms) or not 0 < duration_ms <= MAX_SECONDS * 1000:
        raise SignalError("local_audio_duration_limit")
    if len(turns) > 10_000:
        raise SignalError("local_audio_turn_limit")
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for turn in turns:
        start, end, speaker = turn["start_ms"], turn["end_ms"], turn["speaker_id"]
        if (
            not isinstance(speaker, str)
            or not speaker
            or not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end))
            or not 0 <= start < end <= duration_ms
        ):
            raise SignalError("local_audio_invalid_turn")
        grouped[speaker].append((start, end))
    if len(grouped) > 2:
        raise SignalError("local_audio_speaker_limit")
    merged = {speaker: _union(spans) for speaker, spans in grouped.items()}
    totals = {speaker: sum(e - s for s, e in spans) for speaker, spans in merged.items()}
    total = sum(totals.values())
    events: dict[float, int] = defaultdict(int)
    for spans in merged.values():
        for start, end in spans:
            events[start] += 1
            events[end] -= 1
    active = 0
    previous = 0.0
    speech = overlap = 0.0
    for position, change in sorted(events.items()):
        if active:
            speech += position - previous
        if active > 1:
            overlap += position - previous
        active += change
        previous = position
    ordered = sorted((s, e, sp) for sp, spans in merged.items() for s, e in spans)
    gaps = []
    frontier = 0.0
    frontier_speaker = None
    for start, end, speaker in ordered:
        if frontier_speaker is not None and speaker != frontier_speaker and start >= frontier:
            gaps.append(start - frontier)
        if end > frontier:
            frontier, frontier_speaker = end, speaker
    return {
        "speech_ms": speech,
        "silence_ms": duration_ms - speech,
        "overlap_ms": overlap,
        "speaker_talk_ms": totals,
        "speaker_talk_share": {sp: value / total for sp, value in totals.items()},
        "longest_contiguous_turn_ms": max(
            (e - s for spans in merged.values() for s, e in spans), default=0
        ),
        "nonoverlapping_response_gaps_ms": gaps,
        "roles": "unverified_anonymous_clusters",
        "interruptions": "not_inferred_from_overlap",
        "pace_and_fillers": "require_approved_word_transcript",
    }


def analyze(wav: Path, root: Path) -> dict[str, Any]:
    verify_artifacts(root)
    # Optional imports deliberately stay out of the normal application/import path.
    import sherpa_onnx as s  # type: ignore[import-not-found]
    import soundfile as sf  # type: ignore[import-not-found]

    with sf.SoundFile(str(wav)) as source:
        if source.samplerate != 16000 or source.channels != 1 or source.subtype != "PCM_16":
            raise SignalError("local_audio_pcm_required")
        if not 0 < len(source) <= MAX_SECONDS * 16000:
            raise SignalError("local_audio_duration_limit")
        samples = source.read(dtype="float32")
    vad_config = s.VadModelConfig()
    vad_config.silero_vad.model = str(root / "silero.onnx")
    vad_config.sample_rate = 16000
    vad_config.num_threads = 2
    vad = s.VoiceActivityDetector(vad_config, buffer_size_in_seconds=MAX_SECONDS + 1)
    for index in range(0, len(samples), 512):
        vad.accept_waveform(samples[index : index + 512])
    vad.flush()
    speech = []
    duration_ms = len(samples) / 16
    while not vad.empty():
        region = vad.front
        speech.append(
            {
                "start_ms": region.start / 16,
                "end_ms": min(duration_ms, (region.start + len(region.samples)) / 16),
            }
        )
        vad.pop()
    config = s.OfflineSpeakerDiarizationConfig(
        segmentation=s.OfflineSpeakerSegmentationModelConfig(
            pyannote=s.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(root / "segmentation.int8.onnx")
            ),
            num_threads=2,
        ),
        embedding=s.SpeakerEmbeddingExtractorConfig(
            model=str(root / "embedding.onnx"), num_threads=2
        ),
        clustering=s.FastClusteringConfig(num_clusters=2),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    diarizer = s.OfflineSpeakerDiarization(config)
    turns = [
        {
            "start_ms": max(0, r.start * 1000),
            "end_ms": min(duration_ms, r.end * 1000),
            "speaker_id": f"speaker_{r.speaker}",
        }
        for r in diarizer.process(samples).sort_by_start_time()
    ]
    return {
        "schema": "ac.local-audio-experiment/1",
        "clock": "decoded_audio_track",
        "artifacts": ARTIFACTS,
        "vad_regions": speech,
        "vad_speech_ms": sum(r["end_ms"] - r["start_ms"] for r in speech),
        "vad_silence_ms": duration_ms - sum(r["end_ms"] - r["start_ms"] for r in speech),
        "turns": turns,
        "summary": summarize(turns, duration_ms),
        "quality": "experimental_two_speaker_assumption_not_source_separation",
    }

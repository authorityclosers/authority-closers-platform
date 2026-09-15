"""Read-only, source-bound C1 measurements for the Sales Xray report UI.

The service shapes the immutable C1 payload already persisted by the worker. It
never reads source audio, recomputes features, calls a provider, or infers a
score. SignalLab remains an explicitly unavailable compatibility entry until its
inspected source earns a separate runtime adapter.
"""

from __future__ import annotations

import json
import math
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPES,
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.kernel.authz import ActorContext

MEASUREMENT_VIEW_SCHEMA: Literal["ac.sales-xray.measurement-view/1"] = (
    "ac.sales-xray.measurement-view/1"
)
WAVEFORM_SCHEMA: Literal["ac.sales-xray.waveform/1"] = "ac.sales-xray.waveform/1"
SIGNALLAB_SOURCE_REVISION: Literal["signallab-studio-0.2"] = "signallab-studio-0.2"
SIGNALLAB_UNAVAILABLE_REASON: Literal["source_inspected_adapter_not_implemented"] = (
    "source_inspected_adapter_not_implemented"
)
MAX_PLOT_POINTS = 1200
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class MeasurementPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    start_ms: float = Field(ge=0)
    value: float | None = None


class WaveformPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    start_ms: float = Field(ge=0)
    level: float | None = Field(default=None, ge=0, le=1)


class WaveformEnvelope(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        populate_by_name=True,
    )

    schema_: Literal["ac.sales-xray.waveform/1"] = Field(alias="schema")
    kind: Literal["rms_envelope"]
    duration_ms: int = Field(gt=0)
    points: tuple[WaveformPoint, ...] = Field(max_length=MAX_PLOT_POINTS)


class MeasurementSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    measurement: Literal["dbfs", "f0_hz"]
    label: str = Field(min_length=1, max_length=128)
    unit: Literal["dBFS", "Hz"]
    clock: Literal["decoded_audio_track"]
    window_ms: float = Field(gt=0)
    hop_ms: float = Field(gt=0)
    display_stride: int = Field(ge=1)
    points: tuple[MeasurementPoint, ...] = Field(max_length=MAX_PLOT_POINTS)


class NumericMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    status: Literal["available", "unknown"]
    value: float | None = None
    unit: Literal["dBFS", "Hz", "linear"]
    available_fraction: float | None = Field(default=None, ge=0, le=1)


class AudioAtlasChannel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    channel_index: int = Field(ge=0, le=1)
    label: str = Field(min_length=1, max_length=64)
    usable_frames: int = Field(ge=0)
    partial_frames: int = Field(ge=0)
    invalid_frames: int = Field(ge=0)
    level: NumericMeasurement
    pitch: NumericMeasurement
    peak: NumericMeasurement
    series: tuple[MeasurementSeries, ...] = Field(min_length=2, max_length=2)


class AudioAtlasMeasurements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    status: Literal["available"]
    profile: Literal["audioatlas-native-0.1-40ms-10ms"]
    source_rate: int = Field(gt=0)
    decoded_rate: int = Field(gt=0)
    physical_channels: int = Field(ge=1, le=2)
    sample_count: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    window_ms: float = Field(gt=0)
    hop_ms: float = Field(gt=0)
    clock: Literal["decoded_audio_track"]
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_mapping_status: str = Field(min_length=1, max_length=128)
    container_video_sync_certified: Literal[False]
    channels: tuple[AudioAtlasChannel, ...] = Field(min_length=1, max_length=2)
    warning: str = Field(min_length=1, max_length=1000)


class SignalLabAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    status: Literal["unavailable"]
    reason: Literal["source_inspected_adapter_not_implemented"]
    source_revision: Literal["signallab-studio-0.2"]
    runtime_output: Literal[False]


class MeasurementSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    tenant_id: str = Field(min_length=1, max_length=128)
    recording_id: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str = Field(min_length=1, max_length=32)
    duration_ms: int = Field(gt=0)
    source_rate: int = Field(gt=0)
    decoded_rate: int = Field(gt=0)
    physical_channels: int = Field(ge=1, le=2)
    source_codec: str | None = Field(default=None, max_length=128)
    source_track_start_seconds: float | None = None
    source_track_time_base: str | None = Field(default=None, max_length=128)
    clock: Literal["decoded_audio_track"]
    source_mapping_status: str = Field(min_length=1, max_length=128)
    container_video_sync_certified: Literal[False]


class MeasurementCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=128)
    stage: Literal["C1"]
    revision: str = Field(min_length=1, max_length=128)
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_blob_id: str = Field(min_length=1, max_length=128)


class MeasurementView(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        populate_by_name=True,
    )

    schema_: Literal["ac.sales-xray.measurement-view/1"] = Field(alias="schema")
    availability: Literal["available"]
    source: MeasurementSource
    checkpoint: MeasurementCheckpoint
    audioatlas: AudioAtlasMeasurements
    signallab: SignalLabAvailability


def _conflict() -> ConversationConflict:
    return ConversationConflict("Saved C1 measurements are unavailable.")


def _require_text(value: object, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise _conflict()
    return value


def _require_int(value: object, *, positive: bool = False, nonnegative: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0) or (nonnegative and value < 0):
        raise _conflict()
    return value


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise _conflict()
    return value


def _require_number(value: object, *, nonnegative: bool = False) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _conflict()
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise _conflict()
    return result


def _metric(
    value: object,
    unit: Literal["dBFS", "Hz", "linear"],
    *,
    fraction: object = None,
    nonnegative: bool = False,
) -> NumericMeasurement:
    number = None if value is None else _require_number(value, nonnegative=nonnegative)
    available_fraction = None
    if fraction is not None:
        available_fraction = _require_number(fraction, nonnegative=True)
        if available_fraction > 1:
            raise _conflict()
    try:
        return NumericMeasurement(
            status="available" if number is not None else "unknown",
            value=number,
            unit=unit,
            available_fraction=available_fraction,
        )
    except ValueError:
        raise _conflict() from None


def _series(
    channel: dict[str, object],
    measurement: Literal["dbfs", "f0_hz"],
    label: str,
    unit: Literal["dBFS", "Hz"],
    window_ms: float,
    hop_ms: float,
    duration_ms: int,
) -> MeasurementSeries:
    times = channel.get("time_s")
    values = channel.get(measurement)
    stride = channel.get("display_stride")
    if (
        not isinstance(times, list)
        or not isinstance(values, list)
        or len(times) != len(values)
        or len(times) > MAX_PLOT_POINTS
        or type(stride) is not int
        or stride < 1
    ):
        raise _conflict()
    points: list[MeasurementPoint] = []
    previous = -1.0
    for start_seconds, value in zip(times, values, strict=True):
        start = _require_number(start_seconds, nonnegative=True)
        if start <= previous or start * 1000 > duration_ms:
            raise _conflict()
        measured = (
            None if value is None else _require_number(value, nonnegative=measurement == "f0_hz")
        )
        try:
            point = MeasurementPoint(start_ms=start * 1000, value=measured)
        except ValueError:
            raise _conflict() from None
        points.append(point)
        previous = start
    try:
        return MeasurementSeries(
            measurement=measurement,
            label=label,
            unit=unit,
            clock="decoded_audio_track",
            window_ms=window_ms,
            hop_ms=hop_ms,
            display_stride=stride,
            points=tuple(points),
        )
    except ValueError:
        raise _conflict() from None


def _channel_view(
    channel: dict[str, object],
    *,
    frame_count: int,
    window_ms: float,
    hop_ms: float,
    duration_ms: int,
) -> AudioAtlasChannel:
    channel_index = channel.get("channel")
    if type(channel_index) is not int or not 0 <= channel_index <= 1:
        raise _conflict()
    display_frame_count = _require_int(channel.get("frame_count"), positive=True)
    usable = _require_int(channel.get("usable_frames"), nonnegative=True)
    partial = _require_int(channel.get("partial_frames"), nonnegative=True)
    invalid = _require_int(channel.get("invalid_frames"), nonnegative=True)
    if display_frame_count != frame_count or any(
        count > frame_count for count in (usable, partial, invalid)
    ):
        raise _conflict()
    try:
        result = AudioAtlasChannel(
            channel_index=channel_index,
            label=f"Channel {channel_index + 1}",
            usable_frames=usable,
            partial_frames=partial,
            invalid_frames=invalid,
            level=_metric(channel.get("median_dbfs"), "dBFS"),
            pitch=_metric(
                channel.get("f0_median_hz"),
                "Hz",
                fraction=channel.get("pitch_available_fraction"),
                nonnegative=True,
            ),
            peak=_metric(channel.get("max_sample_peak"), "linear", nonnegative=True),
            series=(
                _series(channel, "dbfs", "Level", "dBFS", window_ms, hop_ms, duration_ms),
                _series(
                    channel,
                    "f0_hz",
                    "Fundamental frequency",
                    "Hz",
                    window_ms,
                    hop_ms,
                    duration_ms,
                ),
            ),
        )
    except ValueError:
        raise _conflict() from None
    return result


def _display_views(
    display_channels: object,
    *,
    source_channels: int,
    frame_count: int,
    window_ms: float,
    hop_ms: float,
    duration_ms: int,
) -> tuple[AudioAtlasChannel, ...]:
    if (
        not isinstance(display_channels, list)
        or len(display_channels) != source_channels
        or len(display_channels) > 2
        or any(not isinstance(channel, dict) for channel in display_channels)
    ):
        raise _conflict()
    channels = tuple(
        _channel_view(
            channel,
            frame_count=frame_count,
            window_ms=window_ms,
            hop_ms=hop_ms,
            duration_ms=duration_ms,
        )
        for channel in display_channels
    )
    if {channel.channel_index for channel in channels} != set(range(source_channels)):
        raise _conflict()
    return channels


class ConversationMeasurements:
    """Read one authorized recording's persisted C1 measurement summary."""

    def __init__(self, application: ConversationApplication) -> None:
        self.application = application
        self.database = application.database

    async def get(self, actor: ActorContext, recording_id: UUID) -> dict[str, object]:
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        return (await self._from_recording(recording)).model_dump(mode="json", by_alias=True)

    async def waveform_from_recording(self, recording: ConversationRecording) -> dict[str, object]:
        """Project persisted C1 RMS levels for an already-authorized recording."""

        view = await self._from_recording(recording)
        channels = view.audioatlas.channels
        if not channels:
            raise _conflict()
        reference = channels[0].series[0].points
        for channel in channels[1:]:
            points = channel.series[0].points
            if len(points) != len(reference) or any(
                point.start_ms != expected.start_ms
                for point, expected in zip(points, reference, strict=True)
            ):
                raise _conflict()
        projected: list[WaveformPoint] = []
        for index, expected in enumerate(reference):
            amplitudes = []
            for channel in channels:
                measured = channel.series[0].points[index].value
                if measured is not None:
                    amplitudes.append(1.0 if measured >= 0 else max(0.0, 10 ** (measured / 20)))
            projected.append(
                WaveformPoint(
                    start_ms=expected.start_ms,
                    level=max(amplitudes) if amplitudes else None,
                )
            )
        try:
            envelope = WaveformEnvelope(
                schema=WAVEFORM_SCHEMA,
                kind="rms_envelope",
                duration_ms=view.audioatlas.duration_ms,
                points=tuple(projected),
            )
        except ValueError:
            raise _conflict() from None
        return envelope.model_dump(mode="json", by_alias=True)

    async def _from_recording(self, recording: ConversationRecording) -> MeasurementView:
        binding = binding_for(recording)
        c0_payload = {
            "source_sha256": recording.source_sha256,
            "source_bytes": recording.source_bytes,
            "content_type": recording.content_type,
            "permission_reference": str(recording.permission_id),
        }
        canonical_c0 = build_checkpoint(
            binding,
            "C0",
            "recording-v1",
            {},
            (),
            content_hash(c0_payload),
        )
        c0_row = await self.database.scalar(
            select(ConversationCheckpoint)
            .where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.stage == "C0",
                ConversationCheckpoint.cache_key == canonical_c0.cache_key,
                ConversationCheckpoint.erased_at.is_(None),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if c0_row is None or not isinstance(c0_row.payload, dict) or c0_row.payload != c0_payload:
            raise _conflict()
        try:
            actual_c0 = verified_checkpoint(c0_row, binding)
        except ConversationConflict:
            raise
        except (TypeError, ValueError, KeyError):
            raise _conflict() from None
        if actual_c0 != canonical_c0:
            raise _conflict()
        row = await self.database.scalar(
            select(ConversationCheckpoint)
            .where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.stage == "C1",
                ConversationCheckpoint.erased_at.is_(None),
            )
            .order_by(ConversationCheckpoint.created_at.desc(), ConversationCheckpoint.id.desc())
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if row is None or row.feature_blob_id is None or not isinstance(row.payload, dict):
            raise _conflict()
        try:
            checkpoint = verified_checkpoint(row, binding)
        except ConversationConflict:
            raise
        except (TypeError, ValueError, KeyError):
            raise _conflict() from None
        if checkpoint.parents != (("C0", canonical_c0.manifest_sha256),):
            raise _conflict()
        payload = row.payload
        acoustics = payload.get("acoustics")
        timebase = payload.get("timebase")
        compatibility = payload.get("compatibility")
        display = payload.get("display")
        signal_lab = (
            compatibility.get("signallab_source_evidence")
            if isinstance(compatibility, dict)
            else None
        )
        if (
            not isinstance(acoustics, dict)
            or not isinstance(timebase, dict)
            or not isinstance(compatibility, dict)
            or not isinstance(signal_lab, dict)
            or not isinstance(display, dict)
        ):
            raise _conflict()
        feature_sha256 = _require_digest(payload.get("feature_sha256"))
        if (
            checkpoint.stage != "C1"
            or checkpoint.revision not in AUDIOATLAS_RECIPES
            or json.loads(checkpoint.config_json)
            != {
                "decode_rate": AUDIOATLAS_RECIPES[checkpoint.revision],
                "window_profile": "audioatlas-40ms-10ms",
            }
            or payload.get("schema") != "ac.sales-xray.signal-checkpoint/1"
            or payload.get("stage") != "C1"
            or payload.get("source_sha256") != recording.source_sha256
            or payload.get("source_bytes") != recording.source_bytes
            or acoustics.get("source_sha256") != recording.source_sha256
            or acoustics.get("feature_sha256") != feature_sha256
            or timebase.get("clock") != "decoded_audio_track"
            or timebase.get("rate") != acoustics.get("rate")
            or timebase.get("container_video_sync_certified") is not False
            or compatibility.get("interchangeable") is not False
            or signal_lab.get("status") != SIGNALLAB_UNAVAILABLE_REASON
            or signal_lab.get("source_revision") != SIGNALLAB_SOURCE_REVISION
            or signal_lab.get("native_rate_features") is not True
            or signal_lab.get("pitch_rate_hz") != 16000
        ):
            raise _conflict()
        source_rate = _require_int(payload.get("source_rate"), positive=True)
        source_channels = _require_int(payload.get("source_channels"), positive=True)
        decoded_rate = _require_int(acoustics.get("rate"), positive=True)
        sample_count = _require_int(acoustics.get("sample_count"), positive=True)
        duration_ms = _require_int(payload.get("media_duration_ms"), positive=True)
        expected_rate = AUDIOATLAS_RECIPES[checkpoint.revision]
        if (
            source_channels not in (1, 2)
            or decoded_rate != expected_rate
            or acoustics.get("channels") != source_channels
        ):
            raise _conflict()
        if duration_ms != round(sample_count / decoded_rate * 1000):
            raise _conflict()
        window_samples = _require_int(acoustics.get("window_samples"), positive=True)
        hop_samples = _require_int(acoustics.get("hop_samples"), positive=True)
        expected_window_samples = decoded_rate * 40 // 1000
        expected_hop_samples = decoded_rate * 10 // 1000
        expected_rows = (
            (sample_count + expected_hop_samples - 1) // expected_hop_samples
        ) * source_channels
        if (
            window_samples != expected_window_samples
            or hop_samples != expected_hop_samples
            or acoustics.get("header_bytes") != 40
            or acoustics.get("row_bytes") != 66
            or acoustics.get("rows") != expected_rows
            or acoustics.get("uncompressed_payload_bytes") != expected_rows * 66
            or expected_rows > 360_000
        ):
            raise _conflict()
        window_ms = window_samples / decoded_rate * 1000
        hop_ms = hop_samples / decoded_rate * 1000
        if window_ms != 40 or hop_ms != 10:
            raise _conflict()
        source_codec = payload.get("source_codec")
        if source_codec is not None:
            source_codec = _require_text(source_codec, max_length=128)
        source_start = timebase.get("source_track_start_seconds")
        if source_start is not None:
            source_start = _require_number(source_start)
        source_time_base = timebase.get("source_track_time_base")
        if source_time_base is not None:
            source_time_base = _require_text(source_time_base, max_length=128)
        source_mapping_status = _require_text(timebase.get("source_mapping_status"), max_length=128)
        channels = _display_views(
            display.get("channels"),
            source_channels=source_channels,
            frame_count=expected_rows // source_channels,
            window_ms=window_ms,
            hop_ms=hop_ms,
            duration_ms=duration_ms,
        )
        try:
            view = MeasurementView(
                schema_=MEASUREMENT_VIEW_SCHEMA,
                availability="available",
                source=MeasurementSource(
                    tenant_id=str(recording.tenant_id),
                    recording_id=str(recording.id),
                    source_revision=str(recording.source_revision),
                    source_sha256=recording.source_sha256,
                    content_type=recording.content_type,
                    duration_ms=duration_ms,
                    source_rate=source_rate,
                    decoded_rate=decoded_rate,
                    physical_channels=source_channels,
                    source_codec=source_codec,
                    source_track_start_seconds=source_start,
                    source_track_time_base=source_time_base,
                    clock="decoded_audio_track",
                    source_mapping_status=source_mapping_status,
                    container_video_sync_certified=False,
                ),
                checkpoint=MeasurementCheckpoint(
                    id=str(row.id),
                    stage="C1",
                    revision=checkpoint.revision,
                    cache_key=checkpoint.cache_key,
                    manifest_sha256=checkpoint.manifest_sha256,
                    payload_sha256=checkpoint.payload_sha256,
                    feature_blob_id=str(row.feature_blob_id),
                ),
                audioatlas=AudioAtlasMeasurements(
                    status="available",
                    profile=acoustics["profile"],
                    source_rate=source_rate,
                    decoded_rate=decoded_rate,
                    physical_channels=source_channels,
                    sample_count=sample_count,
                    duration_ms=duration_ms,
                    window_ms=window_ms,
                    hop_ms=hop_ms,
                    clock="decoded_audio_track",
                    feature_sha256=feature_sha256,
                    source_mapping_status=source_mapping_status,
                    container_video_sync_certified=False,
                    channels=channels,
                    warning=_require_text(display.get("warning"), max_length=1000),
                ),
                signallab=SignalLabAvailability(
                    status="unavailable",
                    reason=SIGNALLAB_UNAVAILABLE_REASON,
                    source_revision=SIGNALLAB_SOURCE_REVISION,
                    runtime_output=False,
                ),
            )
            return view
        except (TypeError, ValueError, KeyError):
            raise _conflict() from None


__all__ = [
    "ConversationMeasurements",
    "MeasurementView",
    "MEASUREMENT_VIEW_SCHEMA",
    "WaveformEnvelope",
    "WAVEFORM_SCHEMA",
    "MAX_PLOT_POINTS",
]

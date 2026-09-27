from __future__ import annotations

import math

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.measurement_view import (
    MAX_MEASUREMENT_DURATION_MS,
    ConversationMeasurements,
    _channel_view,
    _display_views,
    _validate_measurement_layout,
)
from ac_platform.conversation_intelligence.signals import (
    MAX_ROWS,
    MAX_ROWS_PER_CHANNEL,
)


def _channel(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "channel": 0,
        "frame_count": 100,
        "usable_frames": 99,
        "partial_frames": 1,
        "invalid_frames": 0,
        "max_sample_peak": 0.5,
        "median_dbfs": -12.0,
        "f0_median_hz": 440.0,
        "pitch_available_fraction": 0.99,
        "display_stride": 1,
        "time_s": [0.0, 0.01],
        "dbfs": [-12.0, -11.5],
        "f0_hz": [440.0, None],
    }
    value.update(changes)
    return value


def test_display_views_rejects_duplicate_or_out_of_range_physical_channels() -> None:
    with pytest.raises(ConversationConflict):
        _display_views(
            [_channel(), _channel(channel=0)],
            source_channels=2,
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )
    with pytest.raises(ConversationConflict):
        _display_views(
            [_channel(channel=2)],
            source_channels=1,
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )


def test_display_views_rejects_nan_missing_series_and_invalid_frame_bounds() -> None:
    with pytest.raises(ConversationConflict):
        _display_views(
            [_channel(dbfs=[math.nan, -11.5])],
            source_channels=1,
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )
    missing = _channel()
    missing.pop("f0_hz")
    with pytest.raises(ConversationConflict):
        _display_views(
            [missing],
            source_channels=1,
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )
    with pytest.raises(ConversationConflict):
        _display_views(
            [_channel(usable_frames=101)],
            source_channels=1,
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )


@pytest.mark.parametrize("field", ["f0_median_hz", "max_sample_peak"])
def test_display_views_rejects_negative_pitch_or_peak(field: str) -> None:
    with pytest.raises(ConversationConflict):
        _display_views(
            [_channel(**{field: -1.0})],
            source_channels=1,
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )


def test_display_views_rejects_point_after_decoded_duration() -> None:
    with pytest.raises(ConversationConflict):
        _channel_view(
            _channel(time_s=[0.0, 1.01], dbfs=[-12.0, -11.5], f0_hz=[440.0, 441.0]),
            frame_count=100,
            window_ms=40,
            hop_ms=10,
            duration_ms=1000,
        )


def test_measurement_layout_allows_one_hour_mono_and_stereo_native_payloads() -> None:
    sample_count = 16_000 * 3_600
    for source_channels, expected_rows in (
        (1, MAX_ROWS_PER_CHANNEL),
        (2, MAX_ROWS),
    ):
        assert (
            _validate_measurement_layout(
                sample_count=sample_count,
                hop_samples=160,
                source_channels=source_channels,
                duration_ms=MAX_MEASUREMENT_DURATION_MS,
            )
            == expected_rows
        )


def test_measurement_layout_rejects_duration_and_row_overflow() -> None:
    with pytest.raises(ConversationConflict):
        _validate_measurement_layout(
            sample_count=16_000 * 3_600,
            hop_samples=160,
            source_channels=1,
            duration_ms=MAX_MEASUREMENT_DURATION_MS + 1,
        )

    # One extra decoded sample creates one more frame per channel while the
    # rounded duration remains exactly one hour; the total row cap must still
    # reject the two-channel artifact.
    for source_channels in (1, 2):
        with pytest.raises(ConversationConflict):
            _validate_measurement_layout(
                sample_count=16_000 * 3_600 + 1,
                hop_samples=160,
                source_channels=source_channels,
                duration_ms=MAX_MEASUREMENT_DURATION_MS,
            )


@pytest.mark.asyncio
async def test_waveform_projects_bounded_rms_amplitude_without_channel_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def channel(points: tuple[object, ...]) -> object:
        return type(
            "Channel",
            (),
            {"series": (type("Series", (), {"points": points})(),)},
        )()

    def point(start_ms: float, value: float | None) -> object:
        return type("Point", (), {"start_ms": start_ms, "value": value})()

    view = type(
        "View",
        (),
        {
            "audioatlas": type(
                "AudioAtlas",
                (),
                {
                    "duration_ms": 30,
                    "channels": (
                        channel((point(0.0, -12.0), point(10.0, None), point(20.0, -200.0))),
                        channel((point(0.0, -6.0), point(10.0, -20.0), point(20.0, None))),
                    ),
                },
            )(),
        },
    )()
    service = object.__new__(ConversationMeasurements)

    async def source_bound_view(_recording: object) -> object:
        return view

    monkeypatch.setattr(service, "_from_recording", source_bound_view)
    result = await service.waveform_from_recording(object())

    assert result["schema"] == "ac.sales-xray.waveform/1"
    assert result["kind"] == "rms_envelope"
    assert result["duration_ms"] == 30
    assert result["points"][0] == {
        "start_ms": 0.0,
        "level": pytest.approx(10 ** (-6 / 20)),
    }
    assert result["points"][1] == {"start_ms": 10.0, "level": pytest.approx(0.1)}
    assert result["points"][2] == {"start_ms": 20.0, "level": pytest.approx(10 ** (-200 / 20))}

from __future__ import annotations

import math

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.measurement_view import (
    _channel_view,
    _display_views,
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

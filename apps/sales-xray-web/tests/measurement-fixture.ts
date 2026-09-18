/** Bounded synthetic saved measurement response; no recording or provider data. */
export function measurementFixture() {
  const source = {
    recording_id: "recording-1",
    source_sha256: "ab".repeat(32),
    clock: "decoded_audio_track",
    container_video_sync_certified: false,
    source_rate: 48000,
    decoded_rate: 16000,
    physical_channels: 1,
    duration_ms: 3000,
  };
  return {
    schema: "ac.sales-xray.measurement-view/1",
    availability: "available",
    source,
    checkpoint: {
      stage: "C1",
      cache_key: "cd".repeat(32),
      manifest_sha256: "ef".repeat(32),
      payload_sha256: "12".repeat(32),
    },
    audioatlas: {
      ...source,
      status: "available",
      profile: "audioatlas-native-0.1-40ms-10ms",
      window_ms: 40,
      hop_ms: 10,
      sample_count: 48000,
      feature_sha256: "34".repeat(32),
      channels: [
        {
          channel_index: 0,
          level: {
            status: "available",
            value: -19.25 as number | null,
            unit: "dBFS",
            available_fraction: null,
          },
          pitch: {
            status: "available",
            value: 190 as number | null,
            unit: "Hz",
            available_fraction: 0.4,
          },
          series: [
            {
              measurement: "dbfs",
              unit: "dBFS",
              clock: "decoded_audio_track",
              window_ms: 40,
              hop_ms: 10,
              display_stride: 100,
              points: [
                { start_ms: 0, value: -20 as number | null },
                { start_ms: 1000, value: null as number | null },
                { start_ms: 2000, value: -18.5 as number | null },
              ],
            },
            {
              measurement: "f0_hz",
              unit: "Hz",
              clock: "decoded_audio_track",
              window_ms: 40,
              hop_ms: 10,
              display_stride: 100,
              points: [
                { start_ms: 0, value: 190 as number | null },
                { start_ms: 1000, value: null as number | null },
                { start_ms: 2000, value: 220 as number | null },
              ],
            },
          ],
        },
      ],
    },
    signallab: {
      status: "unavailable",
      reason: "source_inspected_adapter_not_implemented",
      runtime_output: false,
    },
  };
}

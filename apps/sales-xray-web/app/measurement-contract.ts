/** Display only saved, source-bound physical measurements. Never infer a score. */
export type MeasurementPoint = { start_ms: number; value: number | null };
export type MeasurementSeries = {
  measurement: "dbfs" | "f0_hz";
  unit: "dBFS" | "Hz";
  points: MeasurementPoint[];
};
export type MeasurementChannel = {
  channel_index: number;
  level: number | null;
  pitch: number | null;
  pitchCoverage: number | null;
  series: MeasurementSeries[];
};
export type SavedMeasurements = {
  recordingId: string;
  sourceSha256: string;
  durationMs: number;
  channels: MeasurementChannel[];
};

type ObjectValue = Record<string, unknown>;
const HASH = /^[a-f0-9]{64}$/;
function invalid(): never {
  throw new Error("The saved measurements could not be verified.");
}
function object(value: unknown): ObjectValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as ObjectValue;
}
function number(value: unknown, min = -Infinity, max = Infinity): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < min ||
    value > max
  )
    invalid();
  return value;
}
function integer(value: unknown, min: number, max: number): number {
  const result = number(value, min, max);
  if (!Number.isSafeInteger(result)) invalid();
  return result;
}
function literal(value: unknown, expected: unknown) {
  if (value !== expected) invalid();
}
function digest(value: unknown): string {
  if (typeof value !== "string" || !HASH.test(value)) invalid();
  return value;
}
function array(value: unknown, min: number, max: number): unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max)
    invalid();
  return value;
}
function numericMetric(
  value: unknown,
  unit: string,
  min = -Infinity,
  max = Infinity,
) {
  const metric = object(value);
  literal(metric.unit, unit);
  if (metric.status !== "available" && metric.status !== "unknown") invalid();
  literal(metric.value === null, metric.status === "unknown");
  return {
    value: metric.value === null ? null : number(metric.value, min, max),
    coverage:
      metric.available_fraction === null
        ? null
        : number(metric.available_fraction, 0, 1),
  };
}

export function parseSavedMeasurements(
  input: unknown,
  expected: { recordingId: string; sourceSha256: string },
): SavedMeasurements {
  const view = object(input);
  literal(view.schema, "ac.sales-xray.measurement-view/1");
  literal(view.availability, "available");
  const source = object(view.source);
  literal(source.recording_id, expected.recordingId);
  literal(digest(source.source_sha256), digest(expected.sourceSha256));
  literal(source.clock, "decoded_audio_track");
  literal(source.container_video_sync_certified, false);
  const sourceRate = integer(source.source_rate, 1, 384000);
  const decodedRate = integer(source.decoded_rate, 1, 96000);
  const channelCount = integer(source.physical_channels, 1, 2);
  const durationMs = integer(source.duration_ms, 1, 14_400_000);
  const checkpoint = object(view.checkpoint);
  literal(checkpoint.stage, "C1");
  for (const key of ["cache_key", "manifest_sha256", "payload_sha256"])
    digest(checkpoint[key]);
  const atlas = object(view.audioatlas);
  literal(atlas.status, "available");
  literal(atlas.profile, "audioatlas-native-0.1-40ms-10ms");
  literal(atlas.clock, "decoded_audio_track");
  literal(atlas.container_video_sync_certified, false);
  literal(atlas.source_rate, sourceRate);
  literal(atlas.decoded_rate, decodedRate);
  literal(atlas.physical_channels, channelCount);
  literal(atlas.duration_ms, durationMs);
  literal(atlas.window_ms, 40);
  literal(atlas.hop_ms, 10);
  digest(atlas.feature_sha256);
  const sampleCount = integer(atlas.sample_count, 1, decodedRate * 14400);
  // Integer milliseconds may round at the end of a decoded track.
  if (Math.abs((sampleCount * 1000) / decodedRate - durationMs) > 1) invalid();
  const signalLab = object(view.signallab);
  literal(signalLab.status, "unavailable");
  literal(signalLab.reason, "source_inspected_adapter_not_implemented");
  literal(signalLab.runtime_output, false);
  const indexes = new Set<number>();
  const channels = array(atlas.channels, channelCount, channelCount).map(
    (value) => {
      const channel = object(value);
      const channel_index = integer(channel.channel_index, 0, channelCount - 1);
      if (indexes.has(channel_index)) invalid();
      indexes.add(channel_index);
      const level = numericMetric(channel.level, "dBFS");
      const pitch = numericMetric(channel.pitch, "Hz", 0);
      const seriesKinds = new Set<string>();
      const series = array(channel.series, 2, 2).map(
        (value): MeasurementSeries => {
          const raw = object(value);
          const measurement = raw.measurement;
          if (measurement !== "dbfs" && measurement !== "f0_hz") invalid();
          if (seriesKinds.has(measurement)) invalid();
          seriesKinds.add(measurement);
          const unit = measurement === "dbfs" ? "dBFS" : "Hz";
          literal(raw.unit, unit);
          literal(raw.clock, "decoded_audio_track");
          literal(raw.window_ms, atlas.window_ms);
          literal(raw.hop_ms, atlas.hop_ms);
          integer(raw.display_stride, 1, 1_440_000);
          let previous = -1;
          const points = array(raw.points, 0, 1200).map((value) => {
            const point = object(value);
            const start_ms = number(point.start_ms, 0, durationMs);
            if (start_ms <= previous) invalid();
            previous = start_ms;
            return {
              start_ms,
              value:
                point.value === null
                  ? null
                  : number(
                      point.value,
                      measurement === "f0_hz" ? 0 : -Infinity,
                    ),
            };
          });
          return { measurement, unit, points };
        },
      );
      return {
        channel_index,
        level: level.value,
        pitch: pitch.value,
        pitchCoverage: pitch.coverage,
        series,
      };
    },
  );
  return {
    recordingId: expected.recordingId,
    sourceSha256: expected.sourceSha256,
    durationMs,
    channels,
  };
}

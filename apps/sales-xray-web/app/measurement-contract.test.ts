import { describe, expect, it } from "vitest";
import { measurementFixture } from "../tests/measurement-fixture";
import { parseSavedMeasurements } from "./measurement-contract";

const binding = { recordingId: "recording-1", sourceSha256: "ab".repeat(32) };
describe("saved measurement binding", () => {
  it("preserves saved precision, coverage and missing gaps without inventing a score", () => {
    const view = parseSavedMeasurements(measurementFixture(), binding);
    expect(view.channels[0].level).toBe(-19.25);
    expect(view.channels[0].pitchCoverage).toBe(0.4);
    expect(view.channels[0].series[0].points[1].value).toBeNull();
    expect(view).not.toHaveProperty("score");
  });
  it("keeps unavailable values distinct from measured zero", () => {
    const raw = measurementFixture();
    raw.audioatlas.channels[0].level.status = "unknown";
    raw.audioatlas.channels[0].level.value = null;
    raw.audioatlas.channels[0].series[0].points[0].value = 0;
    const view = parseSavedMeasurements(raw, binding);
    expect(view.channels[0].level).toBeNull();
    expect(view.channels[0].series[0].points[0].value).toBe(0);
  });
  it.each([
    [
      "recording",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.source.recording_id = "recording-2";
      },
    ],
    [
      "source hash",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.source.source_sha256 = "bb".repeat(32);
      },
    ],
    [
      "clock",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.source.clock = "container_pts";
      },
    ],
    [
      "window",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.window_ms = 80;
      },
    ],
    [
      "duration",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.sample_count = 96000;
      },
    ],
    [
      "infinite value",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].level.value = Infinity;
      },
    ],
    [
      "negative pitch",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].pitch.value = -1;
      },
    ],
    [
      "invalid coverage",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].pitch.available_fraction = 4;
      },
    ],
    [
      "wrong unit",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].series[0].unit = "Hz";
      },
    ],
    [
      "duplicate time",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].series[0].points[1].start_ms = 0;
      },
    ],
    [
      "past track end",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].series[0].points[2].start_ms = 4000;
      },
    ],
    [
      "oversized plot",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].series[0].points = Array.from(
          { length: 1201 },
          (_, index) => ({ start_ms: index, value: 0 }),
        );
      },
    ],
    [
      "duplicate series",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].series[1] =
          raw.audioatlas.channels[0].series[0];
      },
    ],
    [
      "unknown presented as measured",
      (raw: ReturnType<typeof measurementFixture>) => {
        raw.audioatlas.channels[0].level.value = null;
      },
    ],
  ])("rejects %s mismatches", (_, mutate) => {
    const raw = measurementFixture();
    mutate(raw);
    expect(() => parseSavedMeasurements(raw, binding)).toThrow(
      "could not be verified",
    );
  });
});

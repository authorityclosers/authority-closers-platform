import { describe, expect, it } from "vitest";
import {
  parseWaveform,
  waveformBins,
  type WaveformEnvelope,
} from "./source-waveform";

const measured: WaveformEnvelope = {
  schema: "ac.sales-xray.waveform/1",
  kind: "rms_envelope",
  duration_ms: 5000,
  points: [
    { start_ms: 0, level: 0.2 },
    { start_ms: 1000, level: null },
    { start_ms: 2000, level: 0.8 },
    { start_ms: 4000, level: 0 },
  ],
};

describe("saved audio envelope", () => {
  it("accepts only bounded finite measured amplitudes and ascending source time", () => {
    expect(parseWaveform(measured)).toEqual(measured);
    for (const points of [
      [{ start_ms: -1, level: 0.5 }],
      [{ start_ms: -0.5, level: 0.5 }],
      [{ start_ms: 0, level: 2 }],
      [{ start_ms: 0, level: NaN }],
      [
        { start_ms: 0, level: 0.5 },
        { start_ms: 0, level: 0.6 },
      ],
      [{ start_ms: 5001, level: 0.1 }],
      Array.from({ length: 1201 }, (_, index) => ({
        start_ms: index,
        level: 0.1,
      })),
    ])
      expect(parseWaveform({ ...measured, points })).toBeNull();
  });
  it("preserves missing samples and real silence instead of inventing wave heights", () => {
    expect(waveformBins(measured, 0, 5000, 5)).toEqual([
      0.2,
      null,
      0.8,
      null,
      0,
    ]);
  });
  it("clips to an evidence window and preserves maxima when reducing points", () => {
    expect(waveformBins(measured, 1000, 4000, 3)).toEqual([null, 0.8, null]);
    expect(waveformBins(measured, 0, 5000, 1)).toEqual([0.8]);
    expect(waveformBins(measured, 3000, 1000, 2)).toEqual([null, null]);
  });
});

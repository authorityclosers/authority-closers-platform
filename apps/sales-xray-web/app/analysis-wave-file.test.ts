import { expect, it } from "vitest";

import { envelopeFromSamples, measureFileWave } from "./analysis-wave-file";
import { parseWaveform } from "./source-waveform";

const RATE = 8_000;
const tone = (seconds: number, amplitude: number) =>
  Float32Array.from(
    { length: seconds * RATE },
    (_, index) => Math.sin((index / RATE) * 2 * Math.PI * 220) * amplitude,
  );

it("measures a file the way the server does: the loudest channel's RMS per second", () => {
  const quiet = tone(10, 0.1);
  const loud = tone(10, 0.5);
  // The second half of the call is silent on both channels.
  quiet.fill(0, 5 * RATE);
  loud.fill(0, 5 * RATE);
  const envelope = envelopeFromSamples([quiet, loud], RATE);
  expect(envelope).not.toBeNull();
  expect(envelope!.duration_ms).toBe(10_000);
  expect(envelope!.points).toHaveLength(10);
  expect(envelope!.points[0].start_ms).toBe(0);
  expect(envelope!.points[9].start_ms).toBe(9_000);
  // A sine's RMS is its amplitude / √2; the louder channel wins.
  expect(envelope!.points[0].level).toBeCloseTo(0.5 / Math.SQRT2, 2);
  expect(envelope!.points[9].level).toBe(0);
  // The same contract the panel and the Report read from the server.
  expect(parseWaveform(envelope)).toEqual(envelope);
});

it("keeps a long call within the server's 1,200 points", () => {
  const hour = new Float32Array(3_600 * 100); // an hour at 100 Hz
  const envelope = envelopeFromSamples([hour], 100);
  expect(envelope!.duration_ms).toBe(3_600_000);
  expect(envelope!.points).toHaveLength(1_200);
  expect(envelope!.points[1].start_ms).toBe(3_000);
  expect(parseWaveform(envelope)).not.toBeNull();
});

it("has no wave without samples, and none where the browser can't decode", async () => {
  expect(envelopeFromSamples([], RATE)).toBeNull();
  expect(envelopeFromSamples([new Float32Array(0)], RATE)).toBeNull();
  // Node has no audio decoder: no wave, and the motif stays on screen.
  const file = new File([new Uint8Array([1, 2, 3])], "call.mp3");
  await expect(measureFileWave(file)).resolves.toBeNull();
  // One measurement per file.
  expect(measureFileWave(file)).toBe(measureFileWave(file));
});

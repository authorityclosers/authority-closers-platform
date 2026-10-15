import { expect, it } from "vitest";

import {
  activityBins,
  allocateBars,
  barsByWidth,
  cleanPhases,
  positionIn,
  shares,
  speechFromTranscript,
  splitPair,
  voiceBars,
  stageTints,
} from "./timeline";

const segment = (
  id: string,
  speaker: string | null,
  start: number,
  end: number,
) => ({
  id,
  speaker_id: speaker,
  start_ms: start,
  end_ms: end,
  text: "",
});

it("puts the confirmed seller on top and the prospect below", () => {
  const speech = speechFromTranscript(
    {
      segments: [
        segment("1", "p", 0, 9_000),
        segment("2", "s", 9_000, 12_000),
        segment("3", null, 12_000, 13_000),
      ],
    },
    { top: "s", bottom: "p" },
  );
  expect(speech?.topId).toBe("s");
  expect(speech?.bottomId).toBe("p");
  expect(speech?.top).toEqual([{ start_ms: 9_000, end_ms: 12_000 }]);
  expect(speech?.bottom).toEqual([{ start_ms: 0, end_ms: 9_000 }]);
});

it("without roles draws the two who talked most, the most talkative on top", () => {
  const speech = speechFromTranscript({
    segments: [
      segment("1", "a", 0, 1_000),
      segment("2", "b", 1_000, 5_000),
      segment("3", "c", 5_000, 5_500),
    ],
  });
  expect([speech?.topId, speech?.bottomId]).toEqual(["b", "a"]);
  expect(speechFromTranscript({ segments: [] })).toBeNull();
  expect(speechFromTranscript(undefined)).toBeNull();
});

it("measures the share of each bin a person talked", () => {
  expect(activityBins([{ start_ms: 0, end_ms: 5_000 }], 0, 10_000, 4)).toEqual([
    1, 1, 0, 0,
  ]);
  expect(
    activityBins([{ start_ms: 1_250, end_ms: 2_500 }], 0, 10_000, 4),
  ).toEqual([0.5, 0, 0, 0]);
  // Spans outside the stretch, and an empty stretch, draw nothing.
  expect(
    activityBins([{ start_ms: 20_000, end_ms: 30_000 }], 0, 10_000, 2),
  ).toEqual([0, 0]);
  expect(activityBins([{ start_ms: 0, end_ms: 1 }], 5, 5, 3)).toEqual([
    0, 0, 0,
  ]);
});

it("orders, clips and closes the stages inside the call", () => {
  expect(
    cleanPhases(
      [
        { label: "Close", start_ms: 8_000, end_ms: 99_000 },
        { label: "Open", start_ms: -10, end_ms: 9_000 },
        { label: "Past the end", start_ms: 12_000, end_ms: 13_000 },
      ],
      10_000,
    ),
  ).toEqual([
    { label: "Open", start_ms: 0, end_ms: 8_000 },
    { label: "Close", start_ms: 8_000, end_ms: 10_000 },
  ]);
  expect(cleanPhases(null, 10_000)).toEqual([]);
  expect(cleanPhases([{ label: "x", start_ms: 0, end_ms: 1 }], 0)).toEqual([]);
});

it("shares the wave bars by length, every stage keeping a few", () => {
  const bars = allocateBars([150_000, 285_000, 245_000, 100_000], 96, 3);
  expect(bars.reduce((a, b) => a + b, 0)).toBe(96);
  expect(Math.min(...bars)).toBeGreaterThanOrEqual(3);
  expect(bars[1]).toBeGreaterThan(bars[0]);
  expect(allocateBars([1, 1_000_000], 10, 3)).toEqual([3, 7]);
  expect(allocateBars([])).toEqual([]);
});

it("places times and splits figures honestly", () => {
  expect(positionIn(5, 0, 10)).toBe(0.5);
  expect(positionIn(50, 0, 10)).toBe(1);
  expect(positionIn(5, 10, 10)).toBe(0);
  expect(shares(17, 8)).toEqual([68, 32]);
  expect(shares(0, 0)).toEqual([0, 0]);
  expect(splitPair("62 : 38")).toEqual([62, 38]);
  expect(splitPair("17:8")).toEqual([17, 8]);
  expect(splitPair("25:08 min")).toBeNull();
});

it("shapes who talked by how loud the call was, when that was measured", () => {
  expect(voiceBars([1, 0.5, 0], [0, 0.5, 1])).toEqual({
    top: [1, 0.5, 0],
    bottom: [0, 0.5, 1],
  });
  const shaped = voiceBars([1, 1, 0], [0, 0, 1], [0.5, null, 0.02]);
  expect(shaped.top).toEqual([0.5, 1, 0]);
  // A very quiet stretch with talk still shows a small bar.
  expect(shaped.bottom).toEqual([0, 0, 0.12]);
});

it("gives a stage the call returns to the same tint as before", () => {
  expect(
    stageTints([
      "Opening",
      "Discovery",
      "Presentation",
      "discovery ",
      "Price",
      "Close",
      "Opening",
    ]),
  ).toEqual([0, 1, 2, 1, 3, 0, 0]);
  expect(stageTints([])).toEqual([]);
});

it("gives a short stage held at its minimum width as many bars as fit it", () => {
  // Two 1% stages are drawn 84 px wide, not 9 px: about 9 bars each at the
  // same pitch as the long stage's 78.
  expect(barsByWidth([1, 1, 98])).toEqual([9, 9, 78]);
  // Equal stages share the width equally.
  expect(barsByWidth([1, 1, 1, 1])).toEqual([24, 24, 24, 24]);
  expect(barsByWidth([])).toEqual([]);
});

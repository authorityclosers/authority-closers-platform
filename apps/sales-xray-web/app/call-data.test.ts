import { expect, it } from "vitest";

import {
  interestSeries,
  numbersHeard,
  priceTalk,
  questionsAsked,
  quietPoint,
  scriptMix,
  talkAfter,
  timePromise,
  voiceStats,
} from "./call-data";
import type { Transcript } from "./report-contract";

function call(
  lines: Array<[string, number, number, string]>,
  durationMs = 600_000,
): Transcript {
  return {
    source_sha256: "0".repeat(64),
    revision: "test-r1",
    timebase_id: "1ms",
    duration_ms: durationMs,
    segments: lines.map(([speaker, start, end, text], index) => ({
      id: `s${index + 1}`,
      speaker_id: speaker,
      start_ms: start,
      end_ms: end,
      text,
    })),
  };
}

const opening = call([
  [
    "rep",
    0,
    12_000,
    "नंदलाल जी नमस्ते मेरा नाम मानस है। अभी सही समय है बात करने का?",
  ],
  ["buyer", 12_500, 15_000, "हां बोलो।"],
  [
    "rep",
    15_500,
    40_000,
    "at least मुझे 10 15 minute का time लगेगा। कितने साल से चल रहा है business?",
  ],
  [
    "buyer",
    40_500,
    50_000,
    "10 minute तक चलेगा। 15 बरस से regular कर रहे हैं।",
  ],
  ["rep", 60_000, 70_000, "एक साल का turnover कितना है?"],
  [
    "buyer",
    70_500,
    80_000,
    "हां 1 CR होता है। पांच जैसा 5 CR का काम होता है yearly.",
  ],
  ["buyer", 80_500, 90_000, "15 20 लाख का माल फंसा है, margin 30% रखते हैं।"],
  [
    "rep",
    200_000,
    560_000,
    "इसका price क्या है? अलग अलग category का कीमत अलग है।",
  ],
]);

it("counts talk, words, questions and the longest non-stop talk per voice", () => {
  const [rep, buyer] = voiceStats(opening);
  expect(rep.id).toBe("rep");
  expect(rep.questions).toBe(4);
  expect(buyer.questions).toBe(0);
  expect(rep.longestMs).toBe(360_000);
  expect(rep.share + buyer.share).toBeCloseTo(1, 5);
  expect(buyer.firstLine).toContain("10 minute");
});

it("lists each question sentence separately", () => {
  const texts = questionsAsked(opening).map((row) => row.text);
  expect(texts).toContain("अभी सही समय है बात करने का?");
  expect(texts).toContain("कितने साल से चल रहा है business?");
  expect(texts).not.toContain("नंदलाल जी नमस्ते मेरा नाम मानस है।");
});

it("hears numbers only when they come with a unit", () => {
  const heard = numbersHeard(opening).map((row) => [row.spoken, row.kind]);
  expect(heard).toContainEqual(["1 CR", "money"]);
  expect(heard).toContainEqual(["5 CR", "money"]);
  expect(heard).toContainEqual(["20 लाख", "money"]);
  expect(heard).toContainEqual(["30%", "percent"]);
  expect(heard).toContainEqual(["15 बरस", "time"]);
  // A bare "15" or "10" without a unit is never read as money.
  expect(heard.some(([spoken]) => spoken === "15")).toBe(false);
});

it("finds the time asked for in the opening minutes", () => {
  const promise = timePromise(opening)!;
  expect(promise.upToMinutes).toBe(15);
  expect(promise.segments.map((segment) => segment.id)).toEqual(["s3", "s4"]);
});

it("finds price talk and reads the script mix", () => {
  expect(priceTalk(opening).map((segment) => segment.id)).toEqual(["s8"]);
  const mix = scriptMix(opening);
  expect(mix.devanagari).toBeGreaterThan(0.5);
  expect(mix.devanagari + mix.latin).toBeCloseTo(1, 5);
});

it("shows when the prospect went quiet and how little they said after", () => {
  const series = interestSeries(opening, "buyer");
  expect(series).toHaveLength(10);
  expect(series[1]).toBeGreaterThan(0.4);
  // Nobody spoke from 2:00 to 3:00; after that only the seller talks.
  expect(series[2]).toBeNull();
  expect(series[5]).toBe(0);
  const quiet = quietPoint(series);
  expect(quiet).toBe(2);
  expect(talkAfter(opening, "buyer", quiet! * 60_000)).toBe(0);
});

it("does not call a voice quiet that never talked", () => {
  expect(quietPoint([0, 0, 0, 0])).toBeNull();
  expect(quietPoint([0.5, 0.4, 0.3])).toBeNull();
});

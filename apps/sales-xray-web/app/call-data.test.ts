import { expect, it } from "vitest";

import {
  numbersHeard,
  priceTalk,
  questionsAsked,
  scriptMix,
  talkShareSeries,
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
    "हां turnover ₹1 CR है। ₹5 CR yearly sales होती है.",
  ],
  ["buyer", 80_500, 90_000, "₹20 लाख का माल फंसा है, margin 30% रखते हैं।"],
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
  expect(heard).toContainEqual(["₹1 CR", "money"]);
  expect(heard).toContainEqual(["₹5 CR", "money"]);
  expect(heard).toContainEqual(["₹20 लाख", "money"]);
  expect(heard).toContainEqual(["30%", "percent"]);
  expect(heard).toContainEqual(["15 बरस", "time"]);
  // A bare "15" or "10" without a unit is never read as money.
  expect(heard.some(([spoken]) => spoken === "15")).toBe(false);
});

it("keeps ambiguous magnitudes as quantities without currency evidence", () => {
  const rows = numbersHeard(
    call([
      ["a", 0, 1000, "Sales 10K customers, 10 L tank and 10 thousand users."],
    ]),
  );
  expect(rows.map(({ spoken, kind }) => [spoken, kind])).toEqual([
    ["10K", "quantity"],
    ["10 L", "quantity"],
    ["10 thousand", "quantity"],
  ]);
});

it("recognizes explicit Rs and rupee evidence without a magnitude", () => {
  const rows = numbersHeard(
    call([
      [
        "a",
        0,
        1000,
        "Rs 500; INR 600; ₹700; 500 rupees; USD 800; $900; 1000 dollars; price 750; revenue 10K; 5 thousand users; 10 lakh customers; and 10K.",
      ],
    ]),
  );
  expect(rows.map(({ spoken, kind }) => [spoken, kind])).toEqual([
    ["Rs 500", "money"],
    ["INR 600", "money"],
    ["₹700", "money"],
    ["500 rupees", "money"],
    ["USD 800", "money"],
    ["$900", "money"],
    ["1000 dollars", "money"],
    ["10K", "quantity"],
    ["5 thousand", "quantity"],
    ["10 lakh", "quantity"],
    ["10K", "quantity"],
  ]);
});

it("keeps explicit percent and time units beside money-context words", () => {
  const rows = numbersHeard(
    call([
      [
        "a",
        0,
        1000,
        "Revenue 30 percent; profit 30%; the cost 10 days of downtime.",
      ],
    ]),
  );
  expect(rows.map(({ spoken, kind }) => [spoken, kind])).toEqual([
    ["30 percent", "percent"],
    ["30%", "percent"],
    ["10 days", "time"],
  ]);
});

it("finds the time asked for in the opening minutes", () => {
  const promise = timePromise(opening)!;
  expect(promise.upToMinutes).toBe(15);
  expect(promise.segments.map((segment) => segment.id)).toEqual(["s3"]);
});

it("does not treat unrelated minutes as a time agreement", () => {
  const unrelated = call([
    ["a", 0, 1000, "The meeting starts in 30 minutes."],
    ["b", 2000, 3000, "I waited 10 minutes."],
    ["c", 4000, 5000, "I take 10 minutes to walk to work."],
    ["d", 6000, 7000, "We need 20 minutes to cool the machine."],
  ]);
  expect(timePromise(unrelated)).toBeNull();
});

it("recognizes requested and committed call time in English and Hindi", () => {
  const requested = timePromise(
    call([
      ["a", 0, 1000, "Give me 7 minutes."],
      ["b", 2000, 3000, "I'll call you in 5 minutes."],
      ["c", 4000, 5000, "I'll send it in 10 minutes."],
      ["d", 6000, 7000, "I'll get back to you in 8 minutes."],
      ["e", 8000, 9000, "5 मिनट दीजिए."],
    ]),
  );
  expect(requested?.upToMinutes).toBe(10);
  expect(requested?.segments).toHaveLength(5);
});

it("finds price talk and reads the script mix", () => {
  expect(priceTalk(opening).map((segment) => segment.id)).toEqual(["s8"]);
  const mix = scriptMix(opening);
  expect(mix.devanagari).toBeGreaterThan(0.5);
  expect(mix.devanagari + mix.latin).toBeCloseTo(1, 5);
});

it("reports each voice's talk share in each active minute", () => {
  const series = talkShareSeries(opening, "buyer");
  expect(series).toHaveLength(10);
  expect(series[1]).toBeGreaterThan(0.4);
  // Nobody spoke from 2:00 to 3:00; after that only the seller talks.
  expect(series[2]).toBeNull();
  expect(series[5]).toBe(0);
});

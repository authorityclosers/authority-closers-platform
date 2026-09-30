import { expect, it } from "vitest";

import type { Transcript } from "./report-contract";
import {
  afterPrice,
  confirmedRoles,
  moreSignals,
  ownWords,
  promises,
  talkOvers,
  unansweredQuestions,
} from "./sales-signals";

function call(
  lines: Array<[string, number, number, string]>,
  durationMs = 600_000,
): Transcript {
  return {
    source_sha256: "0".repeat(64),
    revision: "signals-r1",
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

const roles = { seller: "rep", prospect: "buyer" };

const sample = call([
  ["rep", 0, 8_000, "नमस्ते, कितने साल से business चल रहा है?"],
  [
    "buyer",
    8_500,
    20_000,
    "15 साल से। सबसे बड़ी दिक्कत है कि 20 लाख का माल फंसा है।",
  ],
  ["rep", 20_100, 26_000, "अच्छा समझ गया"],
  ["buyer", 30_000, 40_000, "आपका system कैसे काम करता है?"],
  ["buyer", 41_000, 50_000, "और support मिलेगा"],
  ["rep", 48_000, 60_000, "हाँ बिल्कुल मिलेगा, मैं आपको brochure भेज दूंगा।"],
  ["rep", 200_000, 215_000, "इसका price 50 हज़ार है।"],
  ["buyer", 222_000, 230_000, "यह तो बहुत महंगा है।"],
  ["buyer", 240_000, 250_000, "discount मिलेगा?"],
  ["rep", 251_000, 252_000, "देखते हैं"],
  ["rep", 400_000, 410_000, "तो कल 11 बजे meeting fix करते हैं?"],
]);

it("needs a confirmed salesperson or prospect before comparing them", () => {
  expect(confirmedRoles(["rep", "buyer"], {})).toBeNull();
  expect(confirmedRoles(["rep", "buyer"], { rep: "salesperson" })).toEqual(
    roles,
  );
  expect(confirmedRoles(["rep", "buyer"], { buyer: "prospect" })).toEqual(
    roles,
  );
  expect(confirmedRoles(["a", "b", "c"], { a: "you" })).toBeNull();
});

it("finds the prospect's problem in their own words", () => {
  const found = ownWords(sample, roles).map((item) => item.text);
  expect(found).toEqual(["सबसे बड़ी दिक्कत है कि 20 लाख का माल फंसा है।"]);
});

it("flags prospect questions with no reply or a few-word reply", () => {
  const found = unansweredQuestions(sample, roles);
  expect(found.map((item) => [item.segment.id, item.reason])).toEqual([
    ["s9", "very short reply"],
  ]);
});

it("spots the salesperson talking over the prospect", () => {
  const found = talkOvers(sample, roles);
  // s3 starts right after a finished sentence, so it is not a talk-over.
  expect(found.map((item) => item.segment.id)).toEqual(["s6"]);
  expect(found[0].cut).toBe("और support मिलेगा");
  expect(found[0].overlap_ms).toBe(2_000);
});

it("measures the silence after a price and the reply", () => {
  const [price] = afterPrice(sample, roles);
  expect(price.text).toBe("इसका price 50 हज़ार है।");
  expect(price.silence_ms).toBe(7_000);
  expect(price.reply?.text).toBe("यह तो बहुत महंगा है।");
  expect(price.pushback).toBe(true);
});

it("lists promises the salesperson made", () => {
  expect(promises(sample, roles).map((item) => item.text)).toEqual([
    "हाँ बिल्कुल मिलेगा, मैं आपको brochure भेज दूंगा।",
  ]);
});

it("reads the timing signals", () => {
  const more = moreSignals(sample, roles);
  expect(more.first_question_ms).toBe(0);
  expect(more.seller_questions_per_10_min).toBe(2);
  expect(more.longest_answer).toEqual({ start_ms: 48_000, length_ms: 12_000 });
  expect(more.next_step_ms).toBe(400_000);
});

it("reports the prospect's talk-share peak without reading it as openness", () => {
  // Fictional: a buyer reading serial numbers still holds the talk share.
  const reading = call(
    [
      ["rep", 0, 6_000, "Hello, this is a short call about your order."],
      ["buyer", 6_500, 50_000, "Serial one is A1 B2 C3, serial two is D4 E5."],
    ],
    120_000,
  );
  const more = moreSignals(reading, roles);
  expect(more.prospect_peak_ms).toBe(0);
  expect(Object.keys(more)).not.toContain("opened_up_ms");
});

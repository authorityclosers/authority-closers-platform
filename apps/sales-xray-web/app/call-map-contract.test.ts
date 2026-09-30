import { describe, expect, it } from "vitest";
import fixture from "../tests/fixtures/call-map-v1.json";
import {
  CALL_MAP_FAILURE_CODES,
  CallMapContractError,
  parseCallMap,
  SIGNAL_KINDS_V1,
  type CallMap,
} from "./call-map-contract";
import type { TimePromise } from "./call-metrics";
import type { TranscriptSegment } from "./report-contract";

type Draft = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const segments = fixture.segments as TranscriptSegment[];

function draft(): Draft {
  return structuredClone(fixture.call_map);
}

function codeOf(change: (map: Draft) => void, duration = fixture.duration_ms) {
  const map = draft();
  change(map);
  try {
    parseCallMap(map, segments, duration);
  } catch (error) {
    expect(error).toBeInstanceOf(CallMapContractError);
    const { code, message } = error as CallMapContractError;
    expect(message).toBe(code);
    return code;
  }
  return "parsed";
}

describe("parseCallMap", () => {
  it("parses the fictional fixture and fills every field", () => {
    const map = parseCallMap(
      fixture.call_map,
      segments,
      fixture.duration_ms,
    ) as CallMap;
    expect(map).toEqual(fixture.call_map);
    expect(map.time_promise?.promised_ms).toBe(600000);
    expect(map.pains.some((pain) => pain.addressed_by !== null)).toBe(true);
    expect(map.claims.length).toBeGreaterThan(0);
    expect(map.prospect_tasks.length).toBeGreaterThan(0);
    for (const [key, value] of Object.entries(map))
      expect([key, value]).not.toEqual([key, []]);
    const promise: TimePromise | null = map.time_promise;
    expect(promise?.evidence[0].segment_id).toBe("s1");
  });

  it("reads null as not available yet", () => {
    expect(parseCallMap(null, segments, fixture.duration_ms)).toBeNull();
  });

  it("falls back to the last segment end when the duration is missing", () => {
    expect(codeOf(() => {}, null as unknown as number)).toBe("parsed");
    expect(
      codeOf((map) => (map.phases[4].start_ms = 43571), null as never),
    ).toBe("call_map_time_out_of_range");
    const unassigned = [
      ...segments,
      {
        id: "s10",
        speaker_id: null,
        start_ms: 43570,
        end_ms: 50000,
        text: "(noise)",
      },
    ];
    const map = draft();
    map.phases[4].start_ms = 45000;
    expect(() => parseCallMap(map, unassigned, null)).toThrow(
      "call_map_time_out_of_range",
    );
  });

  it.each<[string, (map: Draft) => void]>([
    ["an unknown key", (map) => (map.score_hint = "x")],
    ["an unknown nested key", (map) => (map.speakers[0].name = "Sela")],
    ["a missing field", (map) => delete map.prospect_tasks],
    ["a wrong version", (map) => (map.version = "call-map/2")],
    ["a wrong role", (map) => (map.speakers[0].role = "buyer")],
    ["a wrong phase", (map) => (map.phases[0].name = "small_talk")],
    ["a wrong rung", (map) => (map.outcome.next_step_rung = "soon")],
    ["a wrong intensity", (map) => (map.pains[0].prospect_intensity = "max")],
    ["a wrong period", (map) => (map.money[0].period = "quarter")],
    ["a wrong seller error", (map) => (map.claims[0].seller_error = "tone")],
    ["a wrong gap item", (map) => (map.qualification_gaps[0] = "urgency")],
    ["a wrong polarity", (map) => (map.signals[0].polarity = "neutral")],
    ["a bad pitch id", (map) => (map.pitch_items[0].id = "p1")],
    ["a repeated claim id", (map) => (map.claims[1].id = "cl1")],
    ["zero times", (map) => (map.pains[0].times = 0)],
    ["a string amount", (map) => (map.money[0].value_min = "180")],
    [
      "two promise quotes",
      (map) => map.time_promise.evidence.push(map.time_promise.evidence[0]),
    ],
    ["no phases", (map) => (map.phases = [])],
    ["nine signals", (map) => (map.signals = Array(9).fill(map.signals[0]))],
    [
      "a score word in the verdict",
      (map) => (map.verdict_line = "Seller scored well"),
    ],
    ...[
      "Seller scoring was 8 out of 10",
      "A strong grade for discovery",
      "Seller rating: high",
      "Eight out of ten questions landed",
      "Talk share hit 70 percent",
      "Seller got 7/10 on discovery",
    ].map((verdict): [string, (map: Draft) => void] => [
      `the verdict "${verdict}"`,
      (map) => (map.verdict_line = verdict),
    ]),
  ])("rejects %s as call_map_invalid", (_, change) => {
    expect(codeOf(change)).toBe("call_map_invalid");
  });

  it.each<[string, string, (map: Draft) => void]>([
    [
      "call_map_evidence_unresolved",
      "unknown segment",
      (map) => (map.claims[0].evidence[0].segment_id = "s99"),
    ],
    [
      "call_map_evidence_unresolved",
      "quote not in its segment",
      (map) => (map.money[0].evidence[0].segment_id = "s6"),
    ],
    [
      "call_map_evidence_unresolved",
      "outcome without evidence",
      (map) => (map.outcome.evidence = []),
    ],
    [
      "call_map_time_out_of_range",
      "phase after the end",
      (map) => (map.phases[4].start_ms = 43571),
    ],
    [
      "call_map_time_out_of_range",
      "pitch ends before it starts",
      (map) => (map.pitch_items[0].end_ms = 20200),
    ],
    [
      "call_map_time_out_of_range",
      "promise under a minute",
      (map) => (map.time_promise.promised_ms = 59999),
    ],
    [
      "call_map_phase_order_invalid",
      "phases out of order",
      (map) => (map.phases[2].start_ms = 5400),
    ],
    [
      "call_map_phase_order_invalid",
      "neighbours share a name",
      (map) => (map.phases[2].name = "discovery"),
    ],
    [
      "call_map_reference_unknown",
      "addressed_by names no pitch",
      (map) => (map.pains[0].addressed_by = "pi9"),
    ],
    [
      "call_map_reference_unknown",
      "raised_by names no speaker",
      (map) => (map.pains[0].raised_by = "speaker_9"),
    ],
    [
      "call_map_reference_unknown",
      "a speaker is missing",
      (map) => map.speakers.pop(),
    ],
    [
      "call_map_reference_unknown",
      "a speaker appears twice",
      (map) => (map.speakers[1].speaker_id = "speaker_0"),
    ],
    [
      "call_map_qualification_invalid",
      "an item appears twice",
      (map) => map.qualification_gaps.push("budget"),
    ],
    [
      "call_map_qualification_invalid",
      "an item is missing",
      (map) => map.qualification_gaps.pop(),
    ],
    [
      "call_map_word_cap_exceeded",
      "a 13-word verdict",
      (map) =>
        (map.verdict_line =
          "one two three four five six seven eight nine ten eleven twelve thirteen"),
    ],
    [
      "call_map_word_cap_exceeded",
      "a 9-word signal",
      (map) => (map.signals[0].text = "a b c d e f g h i"),
    ],
    [
      "call_map_word_cap_exceeded",
      "a 7-word money label",
      (map) => (map.money[0].label = "a b c d e f g"),
    ],
    [
      "call_map_money_invalid",
      "min above max",
      (map) => (map.money[0].value_min = 181),
    ],
    [
      "call_map_money_invalid",
      "a negative amount",
      (map) => (map.money[1].value_min = -1),
    ],
    [
      "call_map_money_invalid",
      "a 13-character unit",
      (map) => (map.money[0].unit = "creditsperset"),
    ],
    [
      "call_map_signal_kind_unknown",
      "a risk kind on a forward signal",
      (map) => (map.signals[0].kind = "price_concern"),
    ],
    [
      "call_map_signal_kind_unknown",
      "a kind outside v1",
      (map) => (map.signals[2].kind = "vibe_check"),
    ],
  ])("raises %s for %s", (code, _, change) => {
    expect(codeOf(change)).toBe(code);
  });

  it("uses only the plan's failure codes", () => {
    expect(CALL_MAP_FAILURE_CODES).toHaveLength(9);
    expect(
      CALL_MAP_FAILURE_CODES.every((code) => code.startsWith("call_map_")),
    ).toBe(true);
  });

  it("keeps the v1 signal list per polarity", () => {
    expect(SIGNAL_KINDS_V1.forward).toHaveLength(6);
    expect(SIGNAL_KINDS_V1.risk).toHaveLength(8);
  });

  it("has no scoring word in any key of the parsed map", () => {
    const keys: string[] = [];
    const walk = (value: unknown) => {
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value === "object")
        for (const [key, inner] of Object.entries(value)) {
          keys.push(key);
          walk(inner);
        }
    };
    walk(parseCallMap(fixture.call_map, segments, fixture.duration_ms));
    expect(keys.length).toBeGreaterThan(40);
    expect(
      keys.filter((key) => /score|grade|rating|pass|fail/i.test(key)),
    ).toEqual([]);
  });
});

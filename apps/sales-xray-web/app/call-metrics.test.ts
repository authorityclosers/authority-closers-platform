import { describe, expect, it } from "vitest";
import vectorFile from "../tests/fixtures/call-metrics-vectors.json";
import {
  CALL_METRICS_RULES,
  computeCallMetrics,
  CUT_IN_RULES,
  MONOLOGUE_GAP_MS,
  PRICE_WORDS,
  QUIET_RULES,
  quietFrom,
  timePromiseOverrun,
  type CallMetrics,
  type TimePromise,
} from "./call-metrics";
import type { TranscriptSegment } from "./report-contract";

type Row = [string, string | null, number, number, string];
type Vector = {
  name: string;
  duration_ms: number | null;
  segments: Row[];
  time_promise: TimePromise | null;
  expected: {
    metrics: Omit<CallMetrics, "curve"> & {
      curve: {
        start_ms: number[];
        shares: Record<string, (number | null)[]>;
      };
    };
    quiet: Record<string, { start_ms: number; recovered: boolean } | null>;
    overrun: number | null;
  };
};

const vectors = vectorFile.vectors as unknown as Vector[];

const toSegments = (rows: Row[]): TranscriptSegment[] =>
  rows.map(([id, speaker_id, start_ms, end_ms, text]) => ({
    id,
    speaker_id,
    start_ms,
    end_ms,
    text,
  }));

const segment = (
  id: string,
  speakerId: string,
  startMs: number,
  endMs: number,
): TranscriptSegment => ({
  id,
  speaker_id: speakerId,
  start_ms: startMs,
  end_ms: endMs,
  text: "Fictional line.",
});

describe("call metrics shared vectors (AUT-341 §3.1)", () => {
  it.each(vectors.map((vector) => [vector.name, vector] as const))(
    "%s",
    (_name, vector) => {
      const segments = toSegments(vector.segments);
      const metrics = computeCallMetrics(segments, vector.duration_ms);
      const { curve, ...rest } = vector.expected.metrics;
      expect(metrics).toEqual({
        ...rest,
        curve: curve.start_ms.map((start_ms, index) => ({
          start_ms,
          shares: Object.fromEntries(
            Object.entries(curve.shares).map(([id, shares]) => [
              id,
              shares[index],
            ]),
          ),
        })),
      });
      for (const [speakerId, quiet] of Object.entries(vector.expected.quiet))
        expect(quietFrom(metrics, speakerId)).toEqual(quiet);
      expect(
        timePromiseOverrun(vector.time_promise, segments, metrics.time_used_ms),
      ).toBe(vector.expected.overrun);
    },
  );
});

describe("call metrics rules", () => {
  it("pins the call-metrics/2 timing constants", () => {
    expect(CALL_METRICS_RULES).toBe("call-metrics/2");
    expect(CUT_IN_RULES).toEqual({ overlap_ms: 250, latch_ms: 100 });
    expect(PRICE_WORDS.source).toBe(
      "(budget|बजट|price|प्राइस|कीमत|fees?|फीस|charges|कितने का है|कितने का पड़ेगा)",
    );
  });

  it("joins a speaker's segments at the gap limit and splits just past it", () => {
    const end = 10000;
    const joined = computeCallMetrics(
      [
        segment("a1", "a", 0, end),
        segment("a2", "a", end + MONOLOGUE_GAP_MS, 20000),
      ],
      null,
    );
    expect(joined.monologues).toEqual([
      { speaker_id: "a", start_ms: 0, end_ms: 20000 },
    ]);
    const split = computeCallMetrics(
      [
        segment("a1", "a", 0, end),
        segment("a2", "a", end + MONOLOGUE_GAP_MS + 1, 20000),
      ],
      null,
    );
    expect(split.monologues).toHaveLength(2);
  });

  it("never joins across another speaker's start", () => {
    const metrics = computeCallMetrics(
      [
        segment("a1", "a", 0, 10000),
        segment("b1", "b", 10000, 10500),
        segment("a2", "a", 11000, 20000),
      ],
      null,
    );
    expect(metrics.monologues.map((run) => run.start_ms)).toEqual([
      0, 11000, 10000,
    ]);
  });

  it("finds a quiet run only at the minimum length", () => {
    const bins = QUIET_RULES.min_bins;
    const binMs = QUIET_RULES.bin_ms;
    const lowMs = (binMs * QUIET_RULES.below) / 2;
    const rows = (count: number) =>
      Array.from({ length: count }, (_, index) => [
        segment(`a${index}`, "a", index * binMs, (index + 1) * binMs - lowMs),
        segment(
          `b${index}`,
          "b",
          (index + 1) * binMs - lowMs,
          (index + 1) * binMs,
        ),
      ]).flat();
    expect(quietFrom(computeCallMetrics(rows(bins - 1), null), "b")).toBeNull();
    expect(quietFrom(computeCallMetrics(rows(bins), null), "b")).toEqual({
      start_ms: 0,
      recovered: false,
    });
    expect(
      quietFrom(computeCallMetrics(rows(bins), null), "nobody"),
    ).toBeNull();
  });

  it("returns null for a promise whose evidence segment is unknown", () => {
    const segments = [segment("a1", "a", 0, 10000)];
    const promise = { promised_ms: 1000, evidence: [{ segment_id: "zz" }] };
    expect(timePromiseOverrun(promise, segments, 10000)).toBeNull();
    expect(timePromiseOverrun(null, segments, 10000)).toBeNull();
  });

  it("returns no speakers and no bins for an empty transcript", () => {
    expect(computeCallMetrics([], null)).toEqual({
      time_used_ms: 0,
      speakers: {},
      curve: [],
      monologues: [],
      cut_ins: [],
      price_moments: [],
      longest_reply_after_question: null,
    });
  });
});

import { describe, expect, it } from "vitest";

import {
  duration,
  normalizeMap,
  rupees,
  stageCounts,
  stageMeta,
} from "./call-map-data";

const RAW = {
  schema: "call-data-map/1",
  recording_id: "9dba800c-11de-4564-9e4c-e8b0f2bdfca6",
  submission_id: null,
  workspace: "Authority Closers",
  state: "ready",
  media_ms: 232000,
  cost_inr: 1.234,
  stages: [
    {
      key: "fast",
      label: "Fast pipeline",
      status: "done",
      duration_ms: 11921,
      cost_inr: 0.4496,
      provider: "gemini",
      model: "gemini-3.8-flash",
      version: "fast/1 · call-taxonomy/1",
      counts: { tokens_in: 2522, tokens_out: 2132, attempts: 2 },
    },
    {
      key: "objects",
      label: "Call objects",
      status: "done",
      counts: {
        objects: 21,
        asked: 7,
        auto_filled: 0,
        by_category: { need: 4, people: 3 },
      },
    },
    {
      key: "deep",
      label: "Deep pipeline",
      status: "done",
      counts: {
        segments_labelled: 42,
        audio: "frames",
        tokens_in: 9000,
        tokens_out: 3000,
      },
    },
    {
      key: "objects_updated",
      label: "Objects updated",
      status: "done",
      counts: { objects: 60, superseded: 12, retracted: 2, asked: 3 },
    },
    { key: "odd", status: "exploded", counts: "nope" },
  ],
};

describe("call map data", () => {
  it("gives every stage a safe default", () => {
    const map = normalizeMap(RAW);
    expect(map.workspace).toBe("Authority Closers");
    expect(map.stages).toHaveLength(5);
    expect(map.stages[4]).toMatchObject({
      label: "Stage",
      status: "waiting",
      counts: {},
    });
    expect(normalizeMap(null).stages).toEqual([]);
  });

  it("says each stage's figures in words", () => {
    const [fast, objects, deep, updated] = normalizeMap(RAW).stages;
    expect(stageCounts(deep)).toEqual([
      "42 segments labelled",
      "voice from audio frames",
      "9,000 in / 3,000 out tokens",
    ]);
    expect(stageCounts(updated)).toEqual([
      "60 facts",
      "3 asked",
      "12 superseded",
      "2 retracted",
    ]);
    expect(stageMeta(fast)).toBe(
      "gemini · gemini-3.8-flash · fast/1 · call-taxonomy/1",
    );
    expect(stageCounts(fast)).toEqual([
      "2,522 in / 2,132 out tokens",
      "2 attempts",
    ]);
    expect(stageCounts(objects)).toEqual([
      "21 facts",
      "7 asked",
      "need 4, people 3",
    ]);
    expect(duration(850)).toBe("850 ms");
    expect(duration(11921)).toBe("11.9 s");
    expect(duration(185000)).toBe("3 min 05 s");
    expect(rupees(0.4496)).toBe("₹0.45");
    expect(rupees(0.004)).toBe("under ₹0.01");
    expect(rupees(null)).toBe("");
  });
});

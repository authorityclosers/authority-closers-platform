import { describe, expect, it } from "vitest";

import {
  intentGroup,
  intentMix,
  normalizeEngineObjects,
} from "./engine-objects-data";

const RAW = {
  schema: "call-data-objects/1",
  categories: { need: "Needs and goals", bad: 3 },
  facts: [
    {
      object_id: "o1",
      type: "need.primary_pain",
      category: "need",
      label: "Biggest problem",
      display: "Every sale needs Amit",
      confidence: 0.92,
      basis: "observed",
      status: "asked",
      ai_read: false,
      source: { pipeline: "deep" },
      superseded_a_fast_fact: true,
    },
  ],
  segments: [
    {
      segment_id: "s1",
      start_ms: 0,
      end_ms: 4000,
      speaker: "salesperson",
      intent: "greeting",
      act: "statement",
      topics: ["intro", 4],
    },
    {
      segment_id: "s2",
      start_ms: 4000,
      end_ms: 9000,
      speaker: "prospect",
      intent: "pain",
      act: "statement",
      sentiment: "negative",
    },
  ],
  voice: {
    duration_ms: 9000,
    peaks: [0.1, 0.8],
    speakers: {
      salesperson: { share: 0.45, pace_wpm: 140, pitch_hz: 180, talk_ms: 4000 },
    },
    pauses: { count: 1, long: 0, longest_ms: 1600 },
    overlap_ms: 0,
    source: "audioatlas frames",
  },
};

describe("engine objects data", () => {
  it("normalizes facts, segments and voice with safe defaults", () => {
    const data = normalizeEngineObjects(RAW);
    expect(data.categories).toEqual({ need: "Needs and goals" });
    expect(data.facts[0]).toMatchObject({
      pipeline: "deep",
      replacedFast: true,
      confidence: 0.92,
    });
    expect(data.segments[0].topics).toEqual(["intro"]);
    expect(data.segments[1].sentiment).toBe("negative");
    expect(data.voice?.speakers[0]).toMatchObject({
      label: "salesperson",
      share: 0.45,
      loudnessDbfs: null,
    });
    expect(normalizeEngineObjects({ voice: null }).voice).toBeNull();
    expect(normalizeEngineObjects(null).facts).toEqual([]);
  });

  it("groups intents plainly", () => {
    expect(intentGroup("pricing")).toBe("offer");
    expect(intentGroup("objection_handling")).toBe("friction");
    expect(intentGroup("made_up")).toBe("other");
    expect(intentMix(normalizeEngineObjects(RAW).segments)).toMatchObject({
      opening: 1,
      discovery: 1,
    });
  });
});

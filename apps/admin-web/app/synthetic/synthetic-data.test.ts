import { describe, expect, it } from "vitest";

import {
  humanKey,
  normalizeSyntheticCall,
  normalizeSyntheticIndex,
} from "./synthetic-data";

describe("synthetic dataset browser data", () => {
  it("labels everything synthetic and defaults what is missing", () => {
    const index = normalizeSyntheticIndex({
      items: [
        { call_id: "syn-a-J01-C-01", duration_ms: 60000 },
        { business_id: "no id" },
      ],
      facets: { businesses: [{ value: "syn-a", count: 3 }] },
    });
    expect(index.label).toContain("Synthetic");
    expect(index.items).toHaveLength(1);
    expect(index.items[0]).toMatchObject({
      businessId: "unknown",
      durationMs: 60000,
      outcome: null,
    });
    expect(index.facets.businesses).toEqual([{ value: "syn-a", count: 3 }]);
    const call = normalizeSyntheticCall({
      lines: [{ speaker: "rep", text: "नमस्ते" }],
      answer_key: "bad",
    });
    expect(call.lines[0]).toMatchObject({
      id: "line-0",
      speaker: "rep",
      startMs: 0,
    });
    expect(call.answerKey).toBeNull();
    expect(humanKey("what_worked_and_what_didnt")).toBe(
      "What worked and what didnt",
    );
  });
});

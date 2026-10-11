import { describe, expect, it } from "vitest";

import { eventLabel, normalizeUsage } from "./usage-data";

describe("usage data", () => {
  it("normalizes counts with defaults and readable names", () => {
    const usage = normalizeUsage({
      events: 12,
      by_event: [
        {
          name: "report_pillar_viewed",
          version: "telemetry/1",
          count: 9,
          people: 2,
        },
      ],
      daily: [{ day: "2026-10-11", events: 12 }],
    });
    expect(usage).toMatchObject({
      events: 12,
      people: 0,
      organisations: 0,
      days: 7,
    });
    expect(usage.daily[0]).toEqual({
      day: "2026-10-11",
      events: 12,
      people: 0,
    });
    expect(eventLabel(usage.byEvent[0]!.name)).toBe("Report pillar viewed");
    expect(normalizeUsage(null).byEvent).toEqual([]);
  });
});

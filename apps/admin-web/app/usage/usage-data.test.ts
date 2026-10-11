import { describe, expect, it } from "vitest";

import { eventLabel, journey, normalizeUsage } from "./usage-data";

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

  it("names telemetry/1 events in words and builds the journey from people counts", () => {
    expect(eventLabel("sx.upload_started")).toBe("Upload started");
    expect(eventLabel("sx.something_new")).toBe("Something new");
    const usage = normalizeUsage({
      events: 40,
      by_event: [
        { name: "sx.sign_in", version: "1", count: 20, people: 10 },
        { name: "sx.upload_started", version: "1", count: 9, people: 8 },
        { name: "sx.upload_started", version: "2", count: 3, people: 3 },
        { name: "sx.report_opened", version: "1", count: 8, people: 5 },
      ],
    });
    const { steps, recorded } = journey(usage);
    expect(recorded).toBe(true);
    expect(steps.map((step) => [step.label, step.people])).toEqual([
      ["Signed in", 10],
      ["Upload started", 8],
      ["Upload ended", 0],
      ["Saw an analysis finish", 0],
      ["Opened a report", 5],
      ["Opened Coaching", 0],
      ["Completed a mission", 0],
    ]);
    expect(steps[1]!.share).toBe(0.8);
    expect(journey(normalizeUsage({})).recorded).toBe(false);
  });
});

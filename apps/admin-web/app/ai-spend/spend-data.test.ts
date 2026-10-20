import { describe, expect, it } from "vitest";

import { normalizeAiSpend, rupees, windowLabel } from "./spend-data";

const VIEW = {
  environment: "development",
  generated_at: "2026-10-20T10:00:00+00:00",
  days: 14,
  settings: {
    revision: 2,
    config: { background_enabled: false, daily_cap_inr: 50 },
    history: [
      { revision: 2, reason: "Raised daily from ₹50 to ₹100", at: "x" },
    ],
  },
  features: [
    { key: "canary", label: "Release checks (canary)" },
    { key: "call_data_deep", label: "Call data: deep pipeline" },
  ],
  triggers: { release: "Release check", backfill: "Backfill or bulk re-score" },
  now: { last_24h_inr: 36, month_inr: 40 },
  window: { total_inr: 40, projected_month_inr: 171.43 },
  caps: [
    {
      target: "daily",
      label: "This environment, last 24 hours",
      window: "24h",
      spent_inr: 36,
      cap_inr: 50,
      level: 50,
      raise_to_inr: 100,
    },
  ],
  alerts: [{ target: "daily", level: 50, spent_inr: 36, cap_inr: 50 }],
  series: [
    {
      day: "2026-10-19",
      feature: "canary",
      trigger: "release",
      inr: 6,
      requests: 2,
    },
    {
      day: "2026-10-18",
      feature: "call_data_deep",
      trigger: "backfill",
      inr: 30,
      requests: 9,
    },
    {
      day: "2026-10-19",
      feature: "canary",
      trigger: "release",
      inr: 1,
      requests: 1,
    },
  ],
  models: [
    {
      feature: "canary",
      provider: "gemini",
      model: "gemini-3.8-flash",
      inr: 7,
    },
  ],
  rules: ["Customer call analysis is never stopped by these caps."],
  unpriced_requests: 0,
};

describe("AI spend view", () => {
  it("groups the series by feature and by day, biggest first", () => {
    const data = normalizeAiSpend(VIEW);
    expect(data.environment).toBe("development");
    expect(data.backgroundEnabled).toBe(false);
    expect(
      data.features.map((line) => [line.label, line.inr, line.requests]),
    ).toEqual([
      ["Call data: deep pipeline", 30, 9],
      ["Release checks (canary)", 7, 3],
    ]);
    expect(data.features[1].byTrigger).toEqual([
      { trigger: "release", label: "Release check", inr: 7 },
    ]);
    expect(data.byDay.map((day) => [day.day, day.inr])).toEqual([
      ["2026-10-18", 30],
      ["2026-10-19", 7],
    ]);
    expect(data.caps[0]).toMatchObject({
      target: "daily",
      level: 50,
      raiseToInr: 100,
    });
    expect(data.models[0].feature).toBe("Release checks (canary)");
    expect(data.history[0].reason).toBe("Raised daily from ₹50 to ₹100");
  });

  it("never crashes on an empty or odd body", () => {
    const data = normalizeAiSpend({ caps: [{ level: 70 }], series: "x" });
    expect(data.caps[0].level).toBeNull();
    expect(data.features).toEqual([]);
    expect(normalizeAiSpend(null).environment).toBe("unknown");
  });

  it("says rupees and windows in plain words", () => {
    expect(rupees(1.5)).toBe("₹1.5");
    expect(rupees(1250)).toBe("₹1,250");
    expect(windowLabel("24h")).toBe("last 24 hours");
    expect(windowLabel("daily")).toBe("today");
  });
});

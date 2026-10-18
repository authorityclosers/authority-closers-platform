import { describe, expect, it } from "vitest";

import {
  comparePair,
  costQuery,
  inr,
  normalizeMetrics,
  perMin,
  seconds,
} from "./cost-data";

describe("normalizeMetrics", () => {
  it("never crashes on an empty or broken body", () => {
    const empty = normalizeMetrics({});
    expect(empty.days).toBe(30);
    expect(empty.overview.environments).toEqual([]);
    expect(empty.calls.rows).toEqual([]);
    expect(empty.money.environments).toEqual([]);
    expect(normalizeMetrics(null).pipelines).toEqual([]);
    expect(normalizeMetrics({ overview: "x", calls: 3 }).calls.total).toBe(0);
  });

  it("reads the API's snake_case into the page's shape", () => {
    const metrics = normalizeMetrics({
      window: { days: 7 },
      here: "development",
      sources: [
        {
          environment: "staging",
          generated_at: "2026-10-19T06:00:00Z",
          stale: false,
          copies_counted_upstream: 4,
        },
      ],
      overview: {
        spend_month: 522.42,
        per_minute: 0.663,
        report_p50_ms: 120626,
        environments: [
          { environment: "staging", window: 578.29, per_minute: 0.611 },
        ],
        daily: [
          { day: "2026-10-18", by_environment: { staging: 1.5 }, spend: 1.5 },
        ],
        by_stage: [{ stage: "C2", rupees: 470.78, share: 0.553 }],
      },
      calls: {
        total: 1,
        rows: [
          {
            environment: "staging",
            id: "c1",
            company: "Wise Life",
            stages: {
              C2: { rupees: 3.67, runs: 1 },
              C5: { input_tokens: 5470 },
            },
            rupees: 4.73,
            margin: null,
          },
        ],
      },
      pipelines: [
        {
          id: "v5",
          label: "coaching-v5",
          gold: { reviewed: 6, agreement: 0.667 },
        },
      ],
      money: {
        finding: "Nothing settles by itself.",
        environments: [
          {
            environment: "production",
            open: 83,
            open_rupees: 1312.2,
            by_kind: { canary: 24 },
          },
        ],
      },
    });
    expect(metrics.days).toBe(7);
    expect(metrics.here).toBe("development");
    expect(metrics.sources[0]).toMatchObject({
      environment: "staging",
      copies: 4,
      stale: false,
    });
    expect(metrics.overview.byStage[0]).toMatchObject({
      label: "Transcription",
      share: 0.553,
    });
    expect(metrics.overview.daily[0]?.byEnvironment).toEqual({ staging: 1.5 });
    expect(metrics.calls.rows[0]?.stages.C5?.inputTokens).toBe(5470);
    expect(metrics.calls.rows[0]?.margin).toBeNull();
    expect(metrics.pipelines[0]?.gold.agreement).toBe(0.667);
    expect(metrics.money.environments[0]).toMatchObject({
      open: 83,
      byKind: { canary: 24 },
    });
  });
});

describe("formatting", () => {
  it("shows rupees, per-minute cost and durations plainly", () => {
    expect(inr(4.73)).toBe("₹4.73");
    expect(inr(1312.2)).toBe("₹1,312");
    expect(inr(null)).toBe("–");
    expect(perMin(0.663)).toBe("₹0.66/min");
    expect(seconds(120626)).toBe("2 min 1 s");
    expect(seconds(47520)).toBe("48 s");
    expect(seconds(null)).toBe("–");
  });
});

describe("costQuery", () => {
  const current = { tab: "overview", days: "30", env: "all", tests: false };
  it("keeps the other filters and leaves defaults out of the address", () => {
    expect(costQuery(current, {})).toBe("/usage");
    expect(costQuery(current, { env: "staging" })).toBe("/usage?env=staging");
    expect(
      costQuery({ ...current, tab: "calls", days: "7" }, { tests: true }),
    ).toBe("/usage?tab=calls&days=7&tests=1");
  });
});

describe("comparePair", () => {
  const version = (id: string) =>
    normalizeMetrics({ pipelines: [{ id, label: id }] }).pipelines[0]!;
  const pipelines = [version("new"), version("mid"), version("old")];
  it("defaults to the two newest and honours a chosen pair", () => {
    expect(
      comparePair(pipelines, undefined, undefined).map((p) => p?.id),
    ).toEqual(["new", "mid"]);
    expect(comparePair(pipelines, "old", "new").map((p) => p?.id)).toEqual([
      "old",
      "new",
    ]);
    expect(comparePair(pipelines, "gone", undefined).map((p) => p?.id)).toEqual(
      ["new", "mid"],
    );
    expect(comparePair([], undefined, undefined)).toEqual([null, null]);
  });
});

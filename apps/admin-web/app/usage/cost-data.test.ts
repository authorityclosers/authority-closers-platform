import { describe, expect, it } from "vitest";

import {
  chartSeries,
  chartView,
  chartsFrom,
  comparePair,
  correlation,
  costQuery,
  inr,
  normalizeMetrics,
  perMin,
  seconds,
  seriesValue,
  toggleChart,
  together,
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
            company: "Sunrise Rooftops",
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

describe("charts the owner picks and compares", () => {
  const metrics = normalizeMetrics({
    overview: {
      daily: [
        {
          day: "2026-10-17",
          by_environment: { staging: 2 },
          spend: 2,
          audio_minutes: 4,
          per_minute: 0.5,
          calls: 1,
        },
        {
          day: "2026-10-18",
          by_environment: { staging: 4, development: 1 },
          spend: 5,
          audio_minutes: 8,
          per_minute: 0.625,
          calls: 2,
        },
        {
          day: "2026-10-19",
          by_environment: { development: 3 },
          spend: 3,
          audio_minutes: 0,
          per_minute: null,
          calls: 0,
        },
      ],
    },
    providers: {
      daily: [
        {
          day: "2026-10-18",
          provider: "gemini",
          model: "m",
          input_tokens: 1000,
          output_tokens: 200,
          rupees: 2,
        },
        {
          day: "2026-10-17",
          provider: "openai",
          model: "m",
          input_tokens: 10,
          output_tokens: 5,
          rupees: 0.5,
        },
      ],
    },
  });

  it("offers every day series, and each environment and provider that spent", () => {
    const series = chartSeries(metrics);
    expect(series.map((item) => item.key)).toEqual([
      "spend",
      "perMinute",
      "audio",
      "calls",
      "env-staging",
      "env-development",
      "tokens",
      "provider-gemini",
      "provider-openai",
    ]);
    expect(series.find((item) => item.key === "tokens")?.values).toEqual([
      15, 1200, 0,
    ]);
    expect(series.find((item) => item.key === "provider-gemini")?.label).toBe(
      "Gemini spend",
    );
    expect(series.find((item) => item.key === "perMinute")?.values).toEqual([
      0.5,
      0.625,
      null,
    ]);
  });

  it("keeps the chosen charts and the compared pair in the link", () => {
    const keys = chartSeries(metrics).map((item) => item.key);
    expect(chartsFrom(undefined, keys)).toEqual(["spend", "perMinute"]);
    expect(chartsFrom("calls,bogus,calls,spend", keys)).toEqual([
      "calls",
      "spend",
    ]);
    expect(chartsFrom("none", keys)).toEqual([]);
    expect(toggleChart(["spend", "perMinute"], "spend")).toBe("perMinute");
    expect(toggleChart(["spend"], "spend")).toBe("none");
    expect(toggleChart(["spend"], "calls")).toBe("spend,calls");
    const current = {
      tab: "overview",
      days: "7",
      env: "all",
      tests: false,
      charts: "calls",
    };
    expect(costQuery(current, { ca: "spend", cb: "calls" })).toBe(
      "/usage?days=7&charts=calls&ca=spend&cb=calls",
    );
    expect(
      costQuery(
        { ...current, ca: "spend", cb: "calls" },
        { ca: undefined, cb: undefined },
      ),
    ).toBe("/usage?days=7&charts=calls");
    expect(
      chartView({ charts: "spend,calls", ca: "<script>", cb: "calls" }),
    ).toEqual({ charts: "spend,calls", ca: undefined, cb: "calls" });
  });

  it("says in words whether two series move together", () => {
    expect(correlation([1, 2, 3, 4], [2, 4, 6, 8])).toBeCloseTo(1);
    expect(together(correlation([1, 2, 3, 4], [8, 6, 4, 2]))).toBe(
      "move opposite",
    );
    expect(correlation([1, null, 3], [1, 2, 3])).toBeNull();
    expect(together(null)).toBe("too few days to tell");
    expect(seriesValue("tokens", 1200)).toBe("1,200");
    expect(seriesValue("inr", 4.73)).toBe("₹4.73");
  });
});

describe("money in dollars and rupees", () => {
  it("shows dollars first, rupees beside them, and names the one rate", async () => {
    const { money, normalizeMetrics, rateWords, usd, STAGE_LABEL } =
      await import("./cost-data");
    const metrics = normalizeMetrics({
      fx: { currency: "USD", usd_to_inr: 100, set_on: "2026-09-19" },
    });
    // An older answer names no mode: the planning rate.
    expect(metrics.fx).toEqual({
      currency: "USD",
      usdToInr: 100,
      setOn: "2026-09-19",
      mode: "planning",
      planningUsdToInr: 100,
      latest: null,
      unratedSteps: 0,
      problem: null,
    });
    expect(usd(533, metrics.fx)).toBe("$5.33");
    expect(money(533, metrics.fx)).toBe("$5.33 · ₹533.00");
    expect(money(null, metrics.fx)).toBe("–");
    expect(rateWords(metrics.fx)).toMatch(/^₹100 per \$1, set 19 Sept? 2026$/);
    // An older server sends no rate: the sheet's ₹100 is assumed, no date claimed.
    const older = normalizeMetrics({});
    expect(older.fx.usdToInr).toBe(100);
    expect(rateWords(older.fx)).toBe("₹100 per $1");
    expect(STAGE_LABEL.CDF).toBe("Call data · fast");
    expect(STAGE_LABEL.AR).toBe("AI replies");
  });
});

describe("organisation and feature filters", () => {
  it("reads the choices and keeps a valid choice in every link", async () => {
    const { costQuery, normalizeMetrics, scopeView } = await import(
      "./cost-data"
    );
    const metrics = normalizeMetrics({
      filters: { company: null, stage: "CDF" },
      choices: {
        companies: [
          {
            id: "4a1b2c3d-0000-4000-8000-00000000c0de",
            name: "Fictional Co",
            environment: "production",
            rupees: 12.5,
          },
        ],
        stages: [{ stage: "C2", label: "Transcription" }, { stage: "CDF" }],
      },
      overview: {
        by_stage: [
          { stage: "C4", rupees: 1, input_tokens: 9000, output_tokens: 1200 },
          { stage: "C2", rupees: 3, audio_minutes: 12.5 },
        ],
      },
    });
    expect(metrics.filters).toEqual({
      company: null,
      stage: "CDF",
      person: null,
    });
    expect(metrics.choices.stages[1]).toEqual({
      stage: "CDF",
      label: "Call data · fast",
    });
    expect(metrics.overview.byStage[0]).toMatchObject({
      inputTokens: 9000,
      outputTokens: 1200,
    });
    expect(metrics.overview.byStage[1].audioMinutes).toBe(12.5);
    const org = "4a1b2c3d-0000-4000-8000-00000000c0de";
    expect(scopeView({ org, feature: "AR" })).toEqual({ org, feature: "AR" });
    expect(scopeView({ org: "../x", feature: "nope" })).toEqual({
      org: undefined,
      feature: undefined,
    });
    const link = costQuery(
      {
        tab: "overview",
        days: "30",
        env: "all",
        tests: false,
        org,
        feature: "AR",
      },
      { days: "7" },
    );
    expect(link).toBe(`/usage?days=7&org=${org}&feature=AR`);
  });
});

describe("revenue against cost in plain words", () => {
  it("says what came in, what the AI cost and what is left", async () => {
    const { normalizeMetrics, revenueWords } = await import("./cost-data");
    const metrics = normalizeMetrics({
      window: { days: 30 },
      fx: { usd_to_inr: 100, set_on: "2026-09-19" },
      revenue: {
        totals: {
          production: { revenue: 5000, cost: 700, margin: 4300 },
          staging: { revenue: 100, cost: 250, margin: -150 },
        },
      },
    });
    const [production, staging] = revenueWords(metrics);
    expect(production).toContain("customers paid ₹5,000 in the last 30 days");
    expect(production).toContain("cost $7.00 · ₹700.00");
    expect(production).toContain("86% of what came in");
    expect(staging).toContain("test money");
    const idle = normalizeMetrics({
      revenue: {
        totals: { production: { revenue: 0, cost: 12, margin: -12 } },
      },
    });
    expect(revenueWords(idle)[0]).toContain("no money came in");
  });
});

describe("what each feature runs on", () => {
  it("reads each route and says its unit price in dollars and rupees", async () => {
    const { normalizeMetrics, unitWords, CHANGE_AT } = await import(
      "./cost-data"
    );
    const metrics = normalizeMetrics({
      fx: { usd_to_inr: 100 },
      routes: [
        {
          environment: "production",
          stage: "C2",
          provider: "elevenlabs",
          model: "scribe_v2",
          runs: 40,
          last_at: "2026-10-20T10:00:00Z",
          unit: { basis: "per_hour", usd_per_hour: 0.22 },
        },
        {
          environment: "production",
          stage: "C4",
          provider: "gemini",
          model: "gemini-3.8-flash",
          runs: 40,
          unit: {
            basis: "tokens",
            input_usd_per_million: 0.75,
            output_usd_per_million: 3.75,
          },
        },
        {
          environment: "staging",
          stage: "AR",
          provider: "gemini",
          model: "new-model",
          unit: null,
        },
      ],
    });
    const [audio, facts, replies] = metrics.routes;
    expect(audio.label).toBe("Transcription");
    expect(unitWords(audio.unit, metrics.fx)).toBe(
      "$0.22 (₹22.00) an hour of audio",
    );
    expect(unitWords(facts.unit, metrics.fx)).toBe(
      "$0.75 (₹75.00) in · $3.75 (₹375.00) out per million tokens",
    );
    expect(unitWords(replies.unit, metrics.fx)).toContain(
      "No price in the sheet",
    );
    expect(CHANGE_AT.CDF.href).toBe("/sales-xray/call-data");
    expect(CHANGE_AT.QF).toBeUndefined();
  });
});

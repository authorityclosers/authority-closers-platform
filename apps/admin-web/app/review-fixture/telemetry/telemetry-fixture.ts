/**
 * Fictional product telemetry in the API's own shape (ac.sales-xray.product-telemetry/1),
 * for the dev review page and the tests. No real person, workspace or call.
 */
const timing = (
  taps: number,
  p50: number,
  p75: number,
  p95: number,
  slow: number,
) => ({
  taps,
  p50,
  p75,
  p95,
  slow_share: slow,
});

export function telemetryFixture(now: Date, state: "live" | "empty" = "live") {
  const day = (offset: number) => {
    const moment = new Date(now.getTime() - offset * 86_400_000);
    return moment.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  };
  const buckets = [6, 5, 4, 3, 2, 1, 0].map(day);
  if (state === "empty")
    return {
      schema: "ac.sales-xray.product-telemetry/1",
      environment: "development",
      generated_at: now.toISOString(),
      window: "7d",
      filters: { releases: [] },
      rows_read: 0,
      truncated: false,
      totals: { events: 0, people: 0, sessions: 0, workspaces: 0 },
      consent: { people_off: 0, workspaces_off: 0 },
      speed: [],
      vitals: [],
      starts: [],
      screens: { buckets, hourly: false, rows: [], flows: [] },
      funnels: [],
      features: { active_people: 0, rows: [] },
      errors: { scripts: [], apis: [], taps: [], shown: [] },
      mix: { device: [], tier: [], app: [], net: [] },
      unsent: { phones: 0, waiting: 0, refused: 0, oldest_min: null, rows: [] },
      releases: [],
    };
  return {
    schema: "ac.sales-xray.product-telemetry/1",
    environment: "development",
    generated_at: now.toISOString(),
    window: "7d",
    filters: { releases: ["v0.85.0", "v0.86.0"] },
    rows_read: 18_420,
    truncated: false,
    totals: { events: 18_420, people: 46, sessions: 512, workspaces: 9 },
    consent: { people_off: 2, workspaces_off: 1 },
    speed: [
      {
        action: "lead_open",
        label: "Open a lead",
        slow_ms: 1_000,
        ...timing(2_140, 640, 1_180, 2_900, 0.31),
        people: 38,
        devices: 52,
        slow_device_share: 0.4,
        paint_p75: 140,
        results: { settled: 2_050, timeout: 12, no_change: 78 },
        by_tier: [
          { tier: "low", ...timing(820, 1_240, 2_100, 3_800, 0.62) },
          { tier: "mid", ...timing(910, 560, 880, 1_600, 0.18) },
          { tier: "high", ...timing(410, 320, 460, 900, 0.04) },
        ],
        by_device: [
          { device: "phone", ...timing(1_900, 700, 1_260, 3_000, 0.34) },
          { device: "desktop", ...timing(240, 300, 420, 700, 0.03) },
        ],
        by_release: [
          { release: "v0.86.0", ...timing(1_200, 600, 1_100, 2_700, 0.28) },
          { release: "v0.85.0", ...timing(940, 700, 1_300, 3_100, 0.35) },
        ],
      },
      {
        action: "tab_switch",
        label: "Switch tab",
        slow_ms: 500,
        ...timing(3_400, 180, 320, 900, 0.08),
        people: 41,
        devices: 55,
        slow_device_share: 0.09,
        paint_p75: 72,
        results: { settled: 3_100, timeout: 0, no_change: 300 },
        by_tier: [{ tier: "low", ...timing(1_200, 260, 480, 1_100, 0.21) }],
        by_device: [],
        by_release: [],
      },
      {
        action: "call_start",
        label: "Call",
        slow_ms: 1_000,
        ...timing(610, 420, 760, 1_500, 0.12),
        people: 24,
        devices: 30,
        slow_device_share: 0.13,
        paint_p75: 96,
        results: { settled: 540, timeout: 0, no_change: 70 },
        by_tier: [],
        by_device: [],
        by_release: [],
      },
    ],
    vitals: [
      {
        metric: "lcp",
        samples: 480,
        p75: 2_900,
        rating: "needs_improvement",
        shares: { good: 0.58, needs_improvement: 0.3, poor: 0.12 },
        by_device: [
          { device: "phone", samples: 400, p75: 3_200 },
          { device: "desktop", samples: 80, p75: 1_700 },
        ],
        by_screen: [{ screen: "leads", samples: 300, p75: 3_100 }],
      },
      {
        metric: "inp",
        samples: 1_200,
        p75: 180,
        rating: "good",
        shares: { good: 0.8, needs_improvement: 0.15, poor: 0.05 },
        by_device: [],
        by_screen: [],
      },
      {
        metric: "cls",
        samples: 480,
        p75: 40,
        rating: "good",
        shares: { good: 0.93, needs_improvement: 0.05, poor: 0.02 },
        by_device: [],
        by_screen: [],
      },
    ],
    starts: [
      { start: "cold", app: "android", samples: 140, p50: 1_900, p75: 3_400 },
      { start: "warm", app: "web", samples: 260, p50: 700, p75: 1_100 },
    ],
    screens: {
      buckets,
      hourly: false,
      rows: [
        {
          screen: "leads",
          views: 4_200,
          people: 40,
          stay_p50: 46_000,
          exit_share: 0.34,
          heat: [520, 610, 580, 640, 700, 690, 460],
        },
        {
          screen: "lead",
          views: 2_100,
          people: 38,
          stay_p50: 22_000,
          exit_share: 0.12,
          heat: [260, 300, 280, 320, 350, 330, 260],
        },
        {
          screen: "report",
          views: 900,
          people: 30,
          stay_p50: 95_000,
          exit_share: 0.41,
          heat: [100, 140, 120, 150, 160, 130, 100],
        },
        {
          screen: "chats",
          views: 300,
          people: 12,
          stay_p50: 30_000,
          exit_share: 0.2,
          heat: [0, 30, 40, 60, 70, 60, 40],
        },
      ],
      flows: [
        { from: "leads", to: "lead", count: 2_000 },
        { from: "lead", to: "leads", count: 1_700 },
        { from: "calls", to: "report", count: 600 },
      ],
    },
    funnels: [
      {
        key: "report",
        label: "From a report to an outcome",
        steps: [
          { key: "opened", label: "Opened a report", people: 30, share: 1 },
          {
            key: "read",
            label: "Read a section 5 s or more",
            people: 24,
            share: 0.8,
          },
          {
            key: "full",
            label: "Asked for the full report",
            people: 9,
            share: 0.3,
          },
          { key: "outcome", label: "Saved an outcome", people: 6, share: 0.2 },
        ],
      },
      {
        key: "leads",
        label: "From Leads to an outcome",
        steps: [
          { key: "leads", label: "Opened Leads", people: 40, share: 1 },
          { key: "lead", label: "Opened a lead", people: 38, share: 0.95 },
          { key: "call", label: "Called", people: 24, share: 0.6 },
          { key: "outcome", label: "Saved an outcome", people: 6, share: 0.15 },
        ],
      },
    ],
    features: {
      active_people: 46,
      rows: [
        { feature: "leads", label: "Leads", people: 40, share: 0.87 },
        { feature: "report", label: "Reports", people: 30, share: 0.65 },
        {
          feature: "coaching_score",
          label: "AI coaching score",
          people: 24,
          share: 0.52,
        },
        {
          feature: "calling",
          label: "Calling from the app",
          people: 24,
          share: 0.52,
        },
        {
          feature: "full_report",
          label: "Get full report",
          people: 9,
          share: 0.2,
        },
        { feature: "chats", label: "Chats", people: 12, share: 0.26 },
      ],
    },
    errors: {
      scripts: [
        {
          error: "typeerror",
          where: "3f9a21c7",
          kind: "error",
          source: "app",
          count: 41,
          people: 9,
          screens: ["lead", "leads"],
          releases: ["v0.86.0"],
          last_at: now.toISOString(),
        },
        {
          error: "chunkloaderror",
          where: "0b7e44d1",
          kind: "chunk",
          source: "app",
          count: 6,
          people: 5,
          screens: ["report"],
          releases: ["v0.85.0"],
          last_at: now.toISOString(),
        },
      ],
      apis: [
        {
          endpoint: "v1_leads_id_calls",
          count: 33,
          failed: 2,
          p75: 2_400,
          screens: ["lead"],
        },
      ],
      taps: [
        {
          kind: "rage",
          screen: "lead",
          target: "button",
          count: 14,
          people: 6,
        },
        { kind: "dead", screen: "report", target: "text", count: 9, people: 5 },
      ],
      shown: [{ surface: "connection_card", code: "read_failed", count: 7 }],
    },
    mix: {
      device: [
        { value: "phone", people: 40 },
        { value: "desktop", people: 9 },
      ],
      tier: [
        { value: "low", people: 18 },
        { value: "mid", people: 20 },
        { value: "high", people: 8 },
      ],
      app: [
        { value: "android", people: 31 },
        { value: "web", people: 19 },
      ],
      net: [
        { value: "4g", people: 36 },
        { value: "3g", people: 6 },
      ],
    },
    releases: [
      {
        release: "v0.86.0",
        events: 11_000,
        people: 40,
        first_at: now.toISOString(),
        lead_open: timing(1_200, 600, 1_100, 2_700, 0.28),
        script_errors: 41,
      },
      {
        release: "v0.85.0",
        events: 7_420,
        people: 33,
        first_at: new Date(now.getTime() - 3 * 86_400_000).toISOString(),
        lead_open: timing(940, 700, 1_300, 3_100, 0.35),
        script_errors: 6,
      },
    ],
  };
}

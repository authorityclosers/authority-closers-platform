/**
 * Fictional Speed and journeys answers (the API's own shape, telemetry/speed_view.py) for the
 * local review page: "live" is a small pilot like the real one (a handful of people, most
 * numbers on few samples), "empty" a new environment.
 */
type FixtureStat = {
  n: number;
  p50: number | null;
  p75: number | null;
  p95: number | null;
  few: boolean;
};
const stat = (
  n: number,
  p50: number,
  p75: number,
  p95?: number,
): FixtureStat => ({
  n,
  p50,
  p75,
  p95: n >= 20 ? (p95 ?? p75) : null,
  few: n < 5,
});
const none: FixtureStat = {
  n: 0,
  p50: null,
  p75: null,
  p95: null,
  few: true,
};

const frames = (
  sessions: number,
  people: number,
  slow: number,
  frozen: number,
  p90: FixtureStat,
) => ({
  sessions,
  people,
  frames: sessions * 1_800,
  slow_share: slow,
  frozen_share: frozen,
  p90_ms: p90,
});

export function speedFixture(now: Date, state: "live" | "empty") {
  const hours = (count: number) =>
    new Date(now.getTime() - count * 3_600_000).toISOString();
  const frame = {
    environment: "development",
    generated_at: now.toISOString(),
    window: "7d",
    since: hours(168),
    app: null,
    min_p95: 20,
    few: 5,
    truncated: false,
  };
  if (state === "empty")
    return {
      ...frame,
      totals: { people: 0, sessions: 0, events: 0 },
      frames: { all: frames(0, 0, 0, 0, none), by_version: [], by_model: [] },
      apis: {
        calls: 0,
        people: 0,
        screen_views: 0,
        per_100_views: null,
        by_release: [],
        endpoints: [],
      },
      load: {
        lcp_by_tier: [],
        starts: [],
        cpu: {
          tests: 0,
          people: 0,
          all: none,
          bands: { high: 0, mid: 0, low: 0 },
          by_model: [],
        },
      },
      taps: [],
      journey: {
        from: "leads",
        steps: [
          {
            key: "leads",
            label: "Opened Leads",
            people: 0,
            of_first: null,
            of_previous: null,
          },
        ],
      },
    };
  return {
    ...frame,
    totals: { people: 7, sessions: 64, events: 6_412 },
    frames: {
      all: frames(201, 5, 0.62, 0.031, stat(201, 52, 74, 740)),
      by_version: [
        { version: "1.0.38", ...frames(7, 2, 0.71, 0.12, stat(7, 610, 740)) },
        {
          version: "1.0.36",
          ...frames(58, 4, 0.66, 0.02, stat(58, 47, 78, 160)),
        },
        {
          version: "1.0.34",
          ...frames(81, 4, 0.6, 0.018, stat(81, 49, 70, 140)),
        },
        {
          version: "1.0.32",
          ...frames(55, 3, 0.58, 0.015, stat(55, 44, 61, 120)),
        },
      ],
      by_model: [
        {
          model: "fictional-a12",
          ...frames(96, 2, 0.74, 0.04, stat(96, 61, 90, 300)),
        },
        {
          model: "fictional-note-9",
          ...frames(70, 2, 0.55, 0.02, stat(70, 41, 58, 110)),
        },
        {
          model: "fictional-pixel",
          ...frames(31, 1, 0.12, 0, stat(31, 18, 22, 30)),
        },
        { model: "unknown", ...frames(4, 1, 0.4, 0.01, stat(4, 33, 40)) },
      ],
    },
    apis: {
      calls: 41,
      people: 4,
      screen_views: 655,
      per_100_views: 6.3,
      by_release: [
        {
          release: "v1.00.0",
          first_at: hours(20),
          slow_calls: 1,
          screen_views: 38,
          per_100_views: 2.6,
          people: 1,
        },
        {
          release: "v0.99.0",
          first_at: hours(30),
          slow_calls: 0,
          screen_views: 11,
          per_100_views: 0,
          people: 0,
        },
        {
          release: "v0.98.0",
          first_at: hours(52),
          slow_calls: 6,
          screen_views: 96,
          per_100_views: 6.3,
          people: 2,
        },
        {
          release: "v0.97.0",
          first_at: hours(100),
          slow_calls: 34,
          screen_views: 510,
          per_100_views: 6.7,
          people: 4,
        },
      ],
      endpoints: [
        {
          endpoint: "v1_conversation_acquisition_availability",
          calls: 14,
          people: 1,
          wait: none,
          total: stat(14, 9_900, 10_800),
          failed: 0,
          refused: 0,
          screens: ["new_call"],
        },
        {
          endpoint: "v1_updates",
          calls: 9,
          people: 3,
          wait: stat(2, 1_700, 1_900),
          total: stat(9, 4_800, 6_600),
          failed: 0,
          refused: 0,
          screens: ["leads", "home"],
        },
        {
          endpoint: "v1_lead_desk_chats",
          calls: 7,
          people: 2,
          wait: stat(3, 2_100, 2_400),
          total: stat(7, 2_300, 5_700),
          failed: 0,
          refused: 4,
          screens: ["chats"],
        },
        {
          endpoint: "v1_conversation_acquisition_submissions_id_sourc",
          calls: 6,
          people: 2,
          wait: stat(1, 900, 900),
          total: stat(6, 21_000, 58_000),
          failed: 0,
          refused: 0,
          screens: ["report"],
        },
        {
          endpoint: "v1_lead_desk_leads",
          calls: 5,
          people: 3,
          wait: none,
          total: stat(5, 3_900, 5_200),
          failed: 1,
          refused: 0,
          screens: ["leads"],
        },
      ],
    },
    load: {
      lcp_by_tier: [
        { tier: "low", ...stat(3, 5_200, 6_100), rating: "poor" },
        { tier: "mid", ...stat(9, 3_400, 4_700), rating: "poor" },
        { tier: "high", ...stat(214, 1_500, 2_300, 3_900), rating: "good" },
        {
          tier: "unknown",
          ...stat(12, 1_900, 2_600),
          rating: "needs_improvement",
        },
      ],
      starts: [
        {
          app: "android",
          start: "cold",
          what: "page",
          ...stat(31, 1_200, 1_900, 3_200),
        },
        {
          app: "android",
          start: "warm",
          what: "page",
          ...stat(44, 500, 700, 1_400),
        },
        { app: "web", start: "cold", what: "page", ...stat(18, 1_500, 2_000) },
        {
          app: "android",
          start: "cold",
          what: "launch",
          ...stat(26, 700, 1_000, 2_000),
        },
        { app: "android", start: "warm", what: "launch", ...stat(3, 300, 420) },
      ],
      cpu: {
        tests: 23,
        people: 6,
        all: { ...stat(23, 3.4, 6.8, 9.1) },
        bands: { high: 9, mid: 8, low: 6 },
        by_model: [
          {
            model: "fictional-a12",
            people: 2,
            cpu: { n: 8, p50: 8.2, p75: 9.4, p95: null, few: false },
            tier: "low",
            start: stat(8, 1_900, 2_600),
          },
          {
            model: "fictional-note-9",
            people: 2,
            cpu: { n: 7, p50: 4.1, p75: 4.6, p95: null, few: false },
            tier: "mid",
            start: stat(7, 1_100, 1_400),
          },
          {
            model: "fictional-pixel",
            people: 1,
            cpu: { n: 3, p50: 1.9, p75: 2.1, p95: null, few: true },
            tier: "high",
            start: stat(3, 600, 700),
          },
          {
            model: "unknown",
            people: 1,
            cpu: { n: 5, p50: 1.1, p75: 1.3, p95: null, few: false },
            tier: "high",
            start: stat(5, 900, 1_200),
          },
        ],
      },
    },
    taps: [
      {
        action: "lead_open",
        label: "Open a lead",
        slow_ms: 1_000,
        all: stat(212, 180, 320, 1_100),
        by_tier: [
          { tier: "low", ...stat(4, 900, 1_700), slow_share: 0.5 },
          { tier: "mid", ...stat(18, 420, 760), slow_share: 0.11 },
          { tier: "high", ...stat(190, 150, 260, 600), slow_share: 0.02 },
        ],
      },
      {
        action: "tab_switch",
        label: "Switch tab",
        slow_ms: 500,
        all: stat(140, 90, 160, 420),
        by_tier: [
          { tier: "low", ...stat(2, 640, 900), slow_share: 0.5 },
          { tier: "high", ...stat(138, 80, 150, 400), slow_share: 0.03 },
        ],
      },
      {
        action: "sheet_open",
        label: "Open a sheet",
        slow_ms: 500,
        all: stat(77, 120, 210, 1_300),
        by_tier: [
          { tier: "mid", ...stat(9, 380, 1_200), slow_share: 0.33 },
          { tier: "high", ...stat(68, 110, 190, 900), slow_share: 0.04 },
        ],
      },
      {
        action: "call_start",
        label: "Call",
        slow_ms: 1_000,
        all: stat(31, 300, 520, 900),
        by_tier: [
          { tier: "high", ...stat(31, 300, 520, 900), slow_share: 0.03 },
        ],
      },
    ],
    journey: {
      from: "leads",
      steps: [
        {
          key: "leads",
          label: "Opened Leads",
          people: 7,
          of_first: 1,
          of_previous: null,
        },
        {
          key: "lead",
          label: "Opened a lead",
          people: 3,
          of_first: 0.4286,
          of_previous: 0.4286,
        },
        {
          key: "call",
          label: "Started a call",
          people: 3,
          of_first: 0.4286,
          of_previous: 1,
        },
        {
          key: "upload",
          label: "Started an upload",
          people: 2,
          of_first: 0.2857,
          of_previous: 0.6667,
        },
        {
          key: "saved",
          label: "Upload finished",
          people: 2,
          of_first: 0.2857,
          of_previous: 1,
        },
        {
          key: "report",
          label: "Opened a report",
          people: 2,
          of_first: 0.2857,
          of_previous: 1,
        },
      ],
    },
  };
}

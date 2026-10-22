/**
 * Fictional GET /v1/admin/conversation/meter answers for local review of the cost meter
 * (illustrative numbers, never a measurement).
 */
const group = (calls: number, minutes: number, rupees: number) => ({
  calls,
  audio_minutes: minutes,
  rupees,
  per_minute: minutes ? Math.round((rupees / minutes) * 1000) / 1000 : null,
});

export function meterFixture(
  now: Date,
  state: "live" | "stale" | "empty" = "live",
) {
  const ago = (hours: number) =>
    new Date(now.getTime() - hours * 3_600_000).toISOString();
  const empty = state === "empty";
  return {
    environment: "production",
    available: true,
    generated_at: ago(state === "stale" ? 3 : 0.05),
    age_seconds: state === "stale" ? 3 * 3600 : 180,
    targets: [0.4, 0.1],
    fx: {
      currency: "USD",
      mode: "daily",
      usd_to_inr: 94.81,
      set_on: "2026-10-21",
      planning_usd_to_inr: 100,
      latest: { day: "2026-10-21", usd_to_inr: 94.93 },
      unrated_steps: 0,
      problem: null,
    },
    windows: [
      {
        key: "today",
        label: "Today",
        since: ago(6),
        all_in: empty ? group(0, 0, 0) : group(2, 2.5, 0.23),
        full_reports: empty ? group(0, 0, 0) : group(1, 2.2, 0.2),
        short: empty ? group(0, 0, 0) : group(1, 0.3, 0.03),
        not_analysed: { calls: empty ? 0 : 3, audio_minutes: empty ? 0 : 4.1 },
      },
      {
        key: "24h",
        label: "Last 24 hours",
        since: ago(24),
        all_in: group(9, 41.6, 14.1),
        full_reports: group(7, 36.2, 13.2),
        short: group(2, 5.4, 0.9),
        not_analysed: { calls: 6, audio_minutes: 22.8 },
      },
      {
        key: "7d",
        label: "Last 7 days",
        since: ago(24 * 7),
        all_in: group(69, 318.2, 339.8),
        full_reports: group(63, 286.6, 326.0),
        short: group(6, 31.5, 13.8),
        not_analysed: { calls: 46, audio_minutes: 191.1 },
      },
    ],
    by_version: [
      {
        id: "a1b2c3d4e5",
        label:
          "coaching-v3 · one-pass-v1 · gemini-3.8-flash · gemini-3.1-flash-lite",
        ...group(8, 39.4, 3.6),
        full_reports: 6,
        first_at: ago(14),
        last_at: ago(0.4),
      },
      {
        id: "f6e5d4c3b2",
        label: "coaching-v3 · facts-v2 · gemini-3.8-flash · scribe_v2",
        ...group(61, 278.8, 335.6),
        full_reports: 57,
        first_at: ago(24 * 6.5),
        last_at: ago(30),
      },
    ],
    problems: [],
  };
}

/** Normalizer for GET /v1/admin/conversation/usage: counts only. */
import { read } from "../lib/read";

export type Usage = {
  days: number;
  events: number;
  people: number;
  organisations: number;
  byEvent: { name: string; version: string; count: number; people: number }[];
  daily: { day: string; events: number; people: number }[];
};

export function normalizeUsage(raw: unknown): Usage {
  const body = read.object(raw);
  return {
    days: read.number(read.object(body.window).days, 7),
    events: read.number(body.events),
    people: read.number(body.people),
    organisations: read.number(body.organisations),
    byEvent: read.array(body.by_event).map((item) => {
      const row = read.object(item);
      return {
        name: read.string(row.name, "unnamed"),
        version: read.string(row.version),
        count: read.number(row.count),
        people: read.number(row.people),
      };
    }),
    daily: read.array(body.daily).map((item) => {
      const row = read.object(item);
      return {
        day: read.string(row.day),
        events: read.number(row.events),
        people: read.number(row.people),
      };
    }),
  };
}

/** Sales Xray's telemetry/1 events (Strike A, apps/sales-xray-web/app/telemetry.ts) in words. */
const LABELS: Record<string, string> = {
  "sx.sign_in": "Signed in",
  "sx.sign_out": "Signed out",
  "sx.upload_started": "Upload started",
  "sx.upload_finished": "Upload ended",
  "sx.analysis_seen_done": "Saw an analysis finish",
  "sx.report_opened": "Opened a report",
  "sx.pillar_read": "Read a pillar",
  "sx.coaching_opened": "Opened Coaching",
  "sx.clip_played": "Played a clip",
  "sx.paywall_seen": "Saw a paywall",
  "sx.paywall_clicked": "Clicked a paywall",
  "sx.mission_started": "Started a mission",
  "sx.mission_completed": "Completed a mission",
  "sx.prospect_edited": "Edited a prospect",
  "sx.outcome_set": "Set a deal outcome",
  "sx.error_shown": "Saw an error",
};

/** Known events in words; others: "report_pillar_viewed" reads as "Report pillar viewed". */
export const eventLabel = (name: string) => {
  if (LABELS[name]) return LABELS[name];
  const text = name.replace(/^sx\./, "").replace(/[._]/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** The steps of a rep's journey, in order, as telemetry/1 names them. */
export const JOURNEY = [
  "sx.sign_in",
  "sx.upload_started",
  "sx.upload_finished",
  "sx.analysis_seen_done",
  "sx.report_opened",
  "sx.coaching_opened",
  "sx.mission_completed",
] as const;

/**
 * People who sent each journey event in the window. Not a strict funnel:
 * people can skip steps. With several versions of one event, the larger
 * count is used (the people may overlap), so a step never over-counts.
 */
export function journey(usage: Usage) {
  const people = new Map<string, number>();
  for (const row of usage.byEvent)
    people.set(row.name, Math.max(people.get(row.name) ?? 0, row.people));
  const steps = JOURNEY.map((name) => ({
    name,
    label: eventLabel(name),
    people: people.get(name) ?? 0,
  }));
  const base = Math.max(1, ...steps.map((step) => step.people));
  return {
    steps: steps.map((step) => ({ ...step, share: step.people / base })),
    recorded: steps.some((step) => step.people > 0),
  };
}

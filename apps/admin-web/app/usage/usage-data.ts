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

/** "report_pillar_viewed" reads as "Report pillar viewed". */
export const eventLabel = (name: string) => {
  const text = name.replace(/[._]/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

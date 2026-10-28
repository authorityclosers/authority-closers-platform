import type { ActivityItem } from "../../leads/leads-client";
import type { AnalyticsHistory } from "../../organisation/analytics-data";
const names = [
  "Mira Fictional",
  "Tali Example",
  "Lumi Sample",
  "Kiva Fictional",
  "Nova Example",
  "Orin Sample",
  "Ira Fictional",
  "Alexandria Fictional With A Long Name",
];
export const FIXTURE_NOW = "2026-10-28T12:00:00Z";
export const analyticsFixture: AnalyticsHistory = {
  now: FIXTURE_NOW,
  timezone: "Asia/Kolkata",
  cursor: null,
  directoryMissing: false,
  members: names.map((name, index) => ({
    personId: `00000000-0000-4000-8000-${String(index + 11).padStart(12, "0")}`,
    inviteId: null,
    name,
    email: null,
    role: "member",
    status: "active",
    joinedAt: null,
    lastActiveAt: null,
    minutesUsed30d: 0,
    calls30d: 0,
  })),
  items: [],
};
for (let person = 0; person < 7; person++)
  for (let day = 0; day < 60; day++) {
    // Explicit fictional dev events; one seller works leads solely through notes and stage moves.
    const at = new Date(
      Date.parse(FIXTURE_NOW) - day * 86400000 - 3600000,
    ).toISOString();
    const kinds =
      person === 2
        ? (["note", "stage"] as const)
        : (["call", "note", "stage"] as const);
    for (const kind of kinds)
      for (
        let n = 0;
        n < (kind === "call" ? (day * 3 + person) % 7 : (day + person) % 3);
        n++
      ) {
        analyticsFixture.items.push({
          event_id: `fixture-${person}-${day}-${kind}-${n}`,
          lead_id: "fictional-lead",
          lead_name: "Fictional Lead",
          stage_label: null,
          event: {
            kind,
            at,
            actor_person_id: analyticsFixture.members[person].personId,
            actor_name: names[person],
            connected: kind === "call" ? n % 2 === 0 : null,
            duration_seconds: kind === "call" && n % 2 === 0 ? 60 : null,
          },
        } as ActivityItem);
      }
  }

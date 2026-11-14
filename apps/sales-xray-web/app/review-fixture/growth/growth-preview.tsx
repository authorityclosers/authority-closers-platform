"use client";

import {
  PulseTiles,
  RhythmBars,
  SpeedTile,
  hourSlots,
} from "../../performance/growth-visual";
import type {
  Effort,
  SellerEffort,
  SideEffort,
} from "../../performance/performance-client";

/** Fictional numbers in the shape of the owner's own Growth on 13 Nov 2026. */
const side = (values: Partial<SideEffort> = {}): SideEffort => ({
  attempted: 0,
  connected: 0,
  talk_seconds: 0,
  leads_attempted: 0,
  reached: 0,
  interested: 0,
  meetings: 0,
  won: 0,
  worked_interested: 0,
  backlog: 0,
  eligible: 0,
  first_call_minutes: null,
  late: 0,
  missed_calls: 0,
  not_called_back: 0,
  ...values,
});

const seller: SellerEffort = {
  person_id: "fictional-seller",
  name: "Fictional Seller",
  inbound: side({
    attempted: 5,
    connected: 2,
    talk_seconds: 240,
    leads_attempted: 3,
    reached: 1,
  }),
  cold: side(),
  breaks: [],
  unplanned_break_minutes: 0,
  first_call_at: null,
  last_call_at: null,
  tasks_late: 0,
  missing_recordings: 0,
};

const effort: Effort = {
  days: 1,
  start: "2026-11-13",
  end: "2026-11-13",
  team: false,
  sellers: [seller],
  inbound: seller.inbound,
  cold: seller.cold,
  missing_recordings: 0,
};

const call = (at: string) => ({
  event_id: at,
  lead_id: "fictional-lead",
  lead_name: "Fictional Lead",
  stage_label: null,
  event: { kind: "call", at },
});
// One call at 4 pm and three at 5 pm, India time.
const calls = [
  "2026-11-13T10:40:00Z",
  "2026-11-13T11:35:00Z",
  "2026-11-13T11:45:00Z",
  "2026-11-13T11:55:00Z",
].map(call);

export function GrowthPreview({ quiet = false }: { quiet?: boolean }) {
  const shown = quiet
    ? { ...effort, inbound: side(), sellers: [{ ...seller, inbound: side() }] }
    : effort;
  return (
    <main style={{ padding: 16, display: "grid", gap: 10, maxWidth: 480 }}>
      <SpeedTile effort={shown} />
      <PulseTiles effort={shown} />
      <section aria-label="Calls by hour">
        <RhythmBars
          rhythm={{
            status: "ready",
            byHour: true,
            slots: hourSlots(quiet ? [] : (calls as never), "Asia/Kolkata"),
            partial: false,
          }}
        />
      </section>
    </main>
  );
}

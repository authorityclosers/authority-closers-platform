"use client";

import { CallFacts } from "../../call-engine/call-facts";
import type { LeadDetail } from "../../leads/leads-client";

// A fictional lead with one recorded call. The card's own API read is answered
// by the screenshot harness (or shows nothing without it).
const DETAIL = {
  lead: {
    lead_id: "00000000-0000-4000-8000-0000000000aa",
    calls: 1,
    revision: 3,
  },
  events: [
    { kind: "call", at: "2026-10-16T07:20:00Z", submission_id: "fixture-call" },
  ],
} as unknown as LeadDetail;

export function CallFactsFixture() {
  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 16 }}>
      <CallFacts detail={DETAIL} onChanged={() => undefined} />
    </main>
  );
}

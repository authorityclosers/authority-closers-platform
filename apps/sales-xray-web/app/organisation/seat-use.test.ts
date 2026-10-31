import { describe, expect, it } from "vitest";

import type { Effort, SideEffort } from "../performance/performance-client";
import { seatUseFrom } from "./seats-panel";

const side = (attempted: number, talk_seconds: number): SideEffort => ({
  attempted,
  connected: 0,
  talk_seconds,
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
});

const desk = {
  sellers: [
    {
      person_id: "p-seller",
      name: "Fictional Seller",
      inbound: side(300, 3600),
      cold: side(43, 600),
    },
  ],
} as unknown as Effort;

// Persona QA, 31 Oct 2026: Seat use said 0 calls where Analytics said 343.
describe("seat use", () => {
  it("counts the calls Analytics counts, never fewer than the analysed ones", () => {
    const use = seatUseFrom(
      [
        { personId: "p-seller", calls: 0, minutes: 0 },
        { personId: "p-analyst", calls: 5, minutes: 12 },
      ],
      desk,
    );
    expect(use?.get("p-seller")).toEqual({ calls: 343, minutes: 70 });
    expect(use?.get("p-analyst")).toEqual({ calls: 5, minutes: 12 });
  });

  it("waits for either read", () => {
    expect(seatUseFrom(null, null)).toBeNull();
    expect(seatUseFrom(null, desk)?.get("p-seller")?.calls).toBe(343);
  });
});

import { expect, it } from "vitest";

import type { LeadEvent } from "./leads-client";
import { eventText } from "./lead-sheet";

const call = (event: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "call",
    at: "2026-11-13T12:01:10Z",
    actor_name: "Priya Fictional",
    simulated: false,
    duration_seconds: 7,
    ...event,
  }) as LeadEvent;

// Seller Flow 1, F2 (13 Nov 2026): the lead's history said "called · 7s" for a
// back-out from the dialler, its time away read as the call's length. A
// Call-button dial says only that it was dialled (honest numbers, 3 Nov 2026).
it("says a Call-button dial was dialled, never its time away as a call", () => {
  expect(eventText(call({ estimated: true })).title).toBe(
    "Priya Fictional dialled",
  );
  expect(eventText(call({ estimated: true })).title).not.toMatch(/7|called/);
});

// A call logged by hand from another phone keeps the length its seller gave.
it("keeps a logged call's own length", () => {
  expect(eventText(call({ duration_seconds: 194 })).title).toMatch(
    /^Priya Fictional called · /,
  );
  expect(eventText(call({ simulated: true })).title).toMatch(
    /^Priya Fictional made a sample call/,
  );
});

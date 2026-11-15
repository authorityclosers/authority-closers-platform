import { expect, it } from "vitest";

import type { LeadEvent } from "./leads-client";
import { eventText } from "./lead-sheet";

const changed = (event: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "edited",
    at: "2026-11-14T10:00:00Z",
    actor_name: null,
    changed: ["city"],
    ...event,
  }) as LeadEvent;

// Tester report 211 (production 1.58, 14 Nov 2026): a change no person made
// read "The desk changed city", and nobody could tell who the desk was.
it("names who changed a lead in words a seller knows", () => {
  expect(eventText(changed({ actor_name: "Priya Fictional" })).title).toMatch(
    /^Priya Fictional changed city/,
  );
  // The lead rules, a website form, an import or a connected app.
  expect(eventText(changed({})).title).toMatch(/^Sales X-Ray changed city/);
  // A person whose name the app can't read.
  expect(
    eventText(
      changed({ actor_person_id: "0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10" }),
    ).title,
  ).toMatch(/^A teammate changed city/);
  expect(eventText(changed({})).title).not.toMatch(/desk/i);
});

import { expect, it } from "vitest";

import type { LeadEvent } from "./leads-client";
import { eventText } from "./lead-sheet";

// Stage moves in plain sentences (owner, 25 Oct 2026: "New → New Lead" lines
// were hard to read); a new stage list's moves are nobody's work (AUT-2218).
const move = (event: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "stage",
    at: "2026-10-25T05:00:00Z",
    actor_name: "Kavya Fictional",
    stage: "interested",
    stage_label: "Interested",
    from_label: "New Lead",
    ...event,
  }) as LeadEvent;

it("says who moved the lead, to where, and where it was", () => {
  expect(eventText(move({}))).toEqual({
    title: "Kavya Fictional moved this lead to Interested",
    detail: "It was in New Lead",
  });
  expect(
    eventText(
      move({
        action: "close",
        stage_label: "Closed / Lost",
        outcome_reason_label: "Price",
      }),
    ),
  ).toEqual({
    title: "Kavya Fictional closed this lead as Closed / Lost",
    detail: "It was in New Lead · Price",
  });
  expect(eventText(move({ action: "reopen", from_label: null }))).toEqual({
    title: "Kavya Fictional reopened this lead in Interested",
    detail: undefined,
  });
});

it("words a new stage list's moves as the list's, never a person's", () => {
  expect(
    eventText(
      move({
        move_source: "template",
        from_label: "Spoke to owner",
        stage_label: "Discussion Incomplete",
      }),
    ),
  ).toEqual({
    title: "Stages updated: Spoke to owner is now Discussion Incomplete",
    detail: undefined,
  });
  expect(
    eventText(move({ move_source: "template", from_label: null })).title,
  ).toBe("Stages updated: now in Interested");
  expect(eventText(move({ move_source: "template" })).title).not.toMatch(
    /moved/,
  );
});

// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: () => undefined }));

import { eventText } from "./lead-sheet";
import type { LeadEvent } from "./leads-client";

const move = (extra: Partial<LeadEvent>): LeadEvent =>
  ({
    kind: "stage",
    at: "2026-10-24T22:34:00Z",
    actor_name: "You",
    v: 2,
    stage_label: "Discussion Incomplete",
    from_label: "Spoke to owner",
    ...extra,
  }) as LeadEvent;

// AUT-2218, 25 Oct 2026: a new stage list placed eight leads and My work said
// "You moved them to Discussion Incomplete".
describe("a lead placed by a new stage list", () => {
  it("reads as the stages updating, never as someone moving it", () => {
    const text = eventText(move({ move_source: "template" }));
    expect(text.title).toBe(
      "Stages updated: Spoke to owner is now Discussion Incomplete",
    );
    expect(text.title).not.toMatch(/moved/);
  });

  it("still says who moved a lead by hand, in a plain sentence", () => {
    expect(eventText(move({ move_source: "seller" }))).toEqual({
      title: "You moved this lead to Discussion Incomplete",
      detail: "It was in Spoke to owner",
    });
  });
});

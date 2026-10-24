import { describe, expect, it } from "vitest";

import { dayLabel, storyLines } from "./lead-sheet";
import type { LeadDetail, LeadEvent } from "./leads-client";

const NOW = new Date(2026, 9, 22, 18, 0);

function detail(events: Partial<LeadEvent>[], attempts: number): LeadDetail {
  return {
    lead: {
      lead_id: "11111111-1111-4111-8111-111111111111",
      revision: 3,
      name: "Asha Fictional",
      company: null,
      city: null,
      language: null,
      interest: null,
      phone_last4: "3210",
      stage: "interested",
      stage_label: "Site visit booked",
      source: "meta",
      source_label: "Facebook ad",
      owner_person_id: null,
      owner_name: null,
      why: "",
      why_kind: "open",
      next_action_at: new Date(2026, 9, 23, 11, 0).toISOString(),
      created_at: new Date(2026, 9, 19, 18, 0).toISOString(),
      attempts,
      calls: attempts,
      last_result: null,
      last_result_label: null,
      test_data: false,
    },
    phone: null,
    email: null,
    owner_reason: null,
    next_action_note: null,
    fields: [],
    source_fields: [],
    events: events as LeadEvent[],
    can_edit: true,
    can_assign: false,
    reps: [],
    call_mode: "phone",
  };
}

describe("the story so far", () => {
  it("tells where the lead came from, the calls, the last talk and where it stands", () => {
    const lines = storyLines(
      detail(
        [
          {
            kind: "result",
            at: new Date(2026, 9, 22, 15, 0).toISOString(),
            connected: true,
            stage_label: "Site visit booked",
          },
          {
            kind: "result",
            at: new Date(2026, 9, 21, 10, 0).toISOString(),
            connected: false,
            reason_label: "No answer",
          },
        ],
        3,
      ),
      NOW,
    );
    expect(lines[0]).toBe("Came in 3 days ago from Facebook ad.");
    expect(lines[1]).toBe("Tried 3 times, talked once.");
    expect(lines[2]).toBe("Last talk 3 h ago: Site visit booked.");
    expect(lines[3]).toMatch(/^Now: Site visit booked, next call tomorrow /);
  });

  it("says plainly when nobody has called yet, and who added the lead", () => {
    const added = detail([], 0);
    added.lead.source = "manual";
    added.lead.source_label = "Added by hand";
    const lines = storyLines(added, NOW);
    expect(lines[0]).toBe("Added by hand 3 days ago.");
    expect(lines).toContain("Not called yet.");
    expect(lines.some((line) => line.startsWith("Last"))).toBe(false);
  });

  it("counts a call the phone logged from its dialler, as the question above it does", () => {
    const lines = storyLines(
      detail(
        [
          {
            kind: "call",
            via: "phone",
            direction: "outgoing",
            connected: true,
            duration_seconds: 82,
            at: new Date(2026, 9, 22, 17, 58).toISOString(),
          },
        ],
        0,
      ),
      NOW,
    );
    expect(lines).not.toContain("Not called yet.");
    expect(lines[1]).toBe("Tried 1 time, talked once.");
    expect(lines[2]).toMatch(
      /^Last talk .+: 1\u00a0min 22\u00a0s on the phone\.$/,
    );
  });

  it("names the history's days", () => {
    expect(dayLabel(new Date(2026, 9, 22, 9).toISOString(), NOW)).toBe("Today");
    expect(dayLabel(new Date(2026, 9, 21, 9).toISOString(), NOW)).toBe(
      "Yesterday",
    );
    expect(dayLabel(new Date(2026, 9, 19, 9).toISOString(), NOW)).toMatch(
      /19 Oct/,
    );
  });
});

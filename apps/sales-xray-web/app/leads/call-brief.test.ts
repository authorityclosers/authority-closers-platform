import { describe, expect, it } from "vitest";

import { callBrief } from "./call-brief";

const NOW = new Date(2026, 9, 18, 9, 0);

describe("the last call in three lines", () => {
  it("reads the Report's own summary, objection and next step", () => {
    const brief = callBrief(
      {
        report: {
          content: {
            summary: "Older summary.",
            structure: {
              overview: {
                summary:
                  "Asha runs a 12-person agency and wants her team to close faster. She liked the coaching plan. Pricing came up twice.",
              },
              final_call_outcome: {
                outcome: "Follow-up Set",
                follow_up_on: "2026-10-21",
                objections: [{ text: "Needs her partner's yes first" }],
                next_steps: [{ text: "Send the plan PDF", when: "Tuesday" }],
              },
            },
          },
        },
      },
      NOW,
    );
    expect(brief).toEqual({
      summary:
        "Asha runs a 12-person agency and wants her team to close faster. She liked the coaching plan.",
      objection: "Needs her partner's yes first",
      next: {
        text: "Send the plan PDF (Tuesday)",
        at: new Date(2026, 9, 21, 10, 0),
      },
      outcome: "Follow-up Set",
    });
  });

  it("falls back to the pillars, and to the lost reason for a lost call", () => {
    const brief = callBrief(
      {
        report: {
          content: {
            summary: "Synthetic test call. Ravi asked about the price.",
            pillars: { next_step: { text: "Call back after Diwali" } },
            structure: {
              final_call_outcome: {
                outcome: "Lost",
                lost_reason: "Buyer declined and asked to close it",
              },
            },
          },
        },
      },
      NOW,
    );
    expect(brief?.summary).toBe("Ravi asked about the price.");
    expect(brief?.objection).toBe("Buyer declined and asked to close it");
    expect(brief?.next).toEqual({ text: "Call back after Diwali", at: null });
  });

  it("never offers a date in the past, and has nothing for an empty Report", () => {
    const brief = callBrief(
      {
        report: {
          content: {
            structure: { final_call_outcome: { follow_up_on: "2026-10-01" } },
            summary: "Short call.",
          },
        },
      },
      NOW,
    );
    expect(brief?.next).toBeNull();
    expect(callBrief({ report: { content: {} } }, NOW)).toBeNull();
    expect(callBrief(null, NOW)).toBeNull();
  });
});

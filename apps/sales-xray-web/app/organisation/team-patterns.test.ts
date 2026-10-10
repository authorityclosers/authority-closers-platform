import { expect, it } from "vitest";

import {
  extractPattern,
  tallyPatterns,
  type PatternCall,
} from "./team-patterns";

const skill = (id: string, label: string, status: string) => ({
  dimension_id: id,
  label,
  status,
  observation: "Fictional observation.",
  citations: [],
});

const report = (
  kind: string | null,
  statuses: Record<string, string>,
  fixFirst: string | null = null,
) => ({
  submission_id: "fictional",
  report: {
    content: {
      dimensions: Object.entries(statuses).map(([id, status]) =>
        skill(id, id === "discovery" ? "Discovery" : "Closing", status),
      ),
      overview: {
        outcome: kind ? { kind, text: "Fictional.", evidence: [] } : null,
        final_assessment: fixFirst
          ? {
              fix_first: fixFirst,
              repeat: "r",
              next_focus: "n",
              assessment: "a",
            }
          : undefined,
      },
    },
  },
});

const call = (n: number): PatternCall => ({
  id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  ownerName: "Asha Menon",
  label: null,
  createdAt: `2026-10-0${n}T10:00:00Z`,
});

it("reads the outcome, skill labels and first fix a report already gave", () => {
  expect(
    extractPattern(
      report("follow_up", { discovery: "partial" }, "Ask what the budget is."),
    ),
  ).toEqual({
    outcome: "follow_up",
    skills: [{ id: "discovery", label: "Discovery", status: "partial" }],
    fixFirst: "Ask what the budget is.",
  });
  // Unknown outcome kinds are not counted; an empty report counts nothing.
  expect(extractPattern(report("won_big", {}))).toBeNull();
  expect(extractPattern({})).toBeNull();
  expect(extractPattern(null)).toBeNull();
});

it("counts each label once per call and never counts unassessed skills", () => {
  const reads = [
    report("follow_up", { discovery: "partial", closing: "observed" }, "A"),
    report("follow_up", {
      discovery: "insufficient_evidence",
      closing: "not_applicable",
    }),
    report("no_sale", { discovery: "observed", closing: "partial" }, "C"),
  ].map((payload, index) => ({
    call: call(index + 1),
    pattern: extractPattern(payload)!,
  }));
  const tally = tallyPatterns(reads);
  expect(tally.reports).toBe(3);
  expect(tally.outcomes).toEqual([
    { kind: "follow_up", label: "Next step agreed", calls: 2 },
    { kind: "no_sale", label: "No sale", calls: 1 },
  ]);
  // Discovery: 2 gaps of 3 assessed. Closing: 1 of 2 ("Not relevant" is out).
  expect(tally.skills).toEqual([
    { id: "discovery", label: "Discovery", gaps: 2, assessed: 3 },
    { id: "closing", label: "Closing", gaps: 1, assessed: 2 },
  ]);
  expect(tally.fixFirst.map((item) => [item.call.id, item.text])).toEqual([
    [call(1).id, "A"],
    [call(3).id, "C"],
  ]);
});

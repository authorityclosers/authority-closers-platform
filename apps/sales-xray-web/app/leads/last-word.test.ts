// @vitest-environment happy-dom
import { expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: () => null }));

import { lastWord } from "./lead-sheet";
import type { LeadDetail, LeadEvent } from "./leads-client";

const event = (part: Partial<LeadEvent>) =>
  ({ kind: "result", at: "2026-10-27T05:30:00Z", ...part }) as LeadEvent;
const detail = (events: LeadEvent[], attempts: number) =>
  ({ events, lead: { attempts } }) as unknown as Pick<
    LeadDetail,
    "events" | "lead"
  >;
const NOW = new Date("2026-11-01T06:00:00Z");

// Competitor teardown 17 (1 Nov 2026): the last answer and what was said, and
// the tries so far, over "Did you talk to them?".
it("says the last answer, its words and day, and the tries", () => {
  const talked = lastWord(
    detail(
      [
        event({
          connected: true,
          stage_label: "Interested",
          note: "wants  EMI options",
        }),
        event({ kind: "note", note: "not this one" }),
      ],
      3,
    ),
    NOW,
  );
  expect(talked.last).toMatch(/^Last: Interested · “wants EMI options” · /);
  expect(talked.tries).toBe("Tries: 3");
  const missed = lastWord(
    detail(
      [event({ connected: false, reason_label: "No answer", note: null })],
      2,
    ),
    NOW,
  );
  expect(missed.last).toMatch(/^Last: No answer · /);
  expect(missed.tries).toMatch(/^Tries: 2 · last no answer /);
  // A long remark is cut at 40 letters.
  const long = lastWord(
    detail([event({ connected: true, note: "x".repeat(80) })], 1),
    NOW,
  );
  expect(long.last).toContain(`“${"x".repeat(39)}…”`);
  expect(lastWord(detail([], 0), NOW)).toEqual({ last: null, tries: null });
});

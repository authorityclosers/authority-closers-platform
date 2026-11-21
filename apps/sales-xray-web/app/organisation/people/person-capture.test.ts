import { expect, it } from "vitest";

import { captureSummary } from "./person-capture";

const rate = (
  day: string,
  calls: number,
  received: number,
  needs_fix = false,
) => ({
  person_id: "p",
  name: "Asha",
  day,
  calls,
  received,
  analysed: 0,
  rate: calls ? received / calls : 1,
  needs_fix,
});

// sx-redesign fix round (owner 21 Nov 2026): a team member's call capture is
// one status line and one Fix, never a day-by-day wall of red.
it("says a person's call capture in one line, and whether it needs a fix", () => {
  expect(captureSummary([])).toBeNull();
  expect(
    captureSummary([
      rate("2026-11-20", 3, 0, true),
      rate("2026-11-19", 5, 0, true),
    ]),
  ).toEqual({
    line: "8 calls · 0 recordings in the last 2 days",
    needsFix: true,
  });
  expect(captureSummary([rate("2026-11-20", 1, 1)])).toEqual({
    line: "1 call · 1 recording in the last 1 day",
    needsFix: false,
  });
});

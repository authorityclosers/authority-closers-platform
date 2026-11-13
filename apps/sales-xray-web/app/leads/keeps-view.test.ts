import { expect, it } from "vitest";

import { keepsView } from "./work-views";

// Redmi QA (10 Nov 2026): a Home "New leads" tile opened To Call on New Lead,
// and hours later the Leads tab still opened on it. A list Leads was opened
// with from elsewhere is shown, never kept as the last view; what the person
// picks on Leads is.
it("keeps only the lists picked on Leads, never the one it was opened with", () => {
  const tile = { view: "to_call" as const, step: "new" };
  expect(keepsView(tile, tile)).toBe(false);
  expect(keepsView({ ...tile, step: "interested" }, tile)).toBe(true);
  expect(keepsView(tile, null)).toBe(true);
  expect(keepsView({ step: "new" }, {})).toBe(true);
});

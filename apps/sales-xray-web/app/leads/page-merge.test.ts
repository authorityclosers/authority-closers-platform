import { expect, it } from "vitest";

import { withoutRepeats } from "./page-merge";

// Owner's bug report (31 Oct 2026): leads repeated after the first page.
const row = (id: string) => ({ lead_id: id, name: `Fictional ${id}` });

it("adds a page's leads once, in the order shown", () => {
  const first = ["a", "b", "c"].map(row);
  const next = ["c", "d", "d", "e"].map(row);
  expect(withoutRepeats(first, next).map((item) => item.lead_id)).toEqual([
    "a",
    "b",
    "c",
    "d",
    "e",
  ]);
  expect(withoutRepeats([], first)).toEqual(first);
});

it("pages through 1,000 leads whose pages overlap, each lead once", () => {
  const all = Array.from({ length: 1000 }, (_, n) => row(`lead-${n}`));
  let shown: ReturnType<typeof row>[] = [];
  // Pages of 50, each repeating the last 5 leads of the page before.
  for (let start = 0; start < all.length; start += 45)
    shown = withoutRepeats(shown, all.slice(start, start + 50));
  expect(shown).toHaveLength(1000);
  expect(new Set(shown.map((item) => item.lead_id)).size).toBe(1000);
  expect(shown.map((item) => item.lead_id)).toEqual(
    all.map((item) => item.lead_id),
  );
});

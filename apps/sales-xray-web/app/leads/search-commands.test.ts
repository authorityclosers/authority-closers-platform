import { expect, it, vi } from "vitest";

import type { LeadRow } from "./leads-client";
import { leadSearchCommands } from "./search-commands";

const row = (n: number, phone = true) =>
  ({
    lead_id: `lead-${n}`,
    name: `Fictional ${n}`,
    stage_label: "New",
    city: null,
    phone_last4: phone ? "3210" : null,
  }) as unknown as LeadRow;

// ph2-27 (phone QA, 1 Nov 2026): no full-width Call rows, and a way past six.
it("gives each lead one row with Call beside it, six at most, then Show all", () => {
  const act = { open: vi.fn(), call: vi.fn(), showAll: vi.fn() };
  const leads = [1, 2, 3, 4, 5, 6, 7].map((n) => row(n, n !== 2));
  const found = leadSearchCommands(leads, " fic ", act);
  expect(found.map((item) => item.label)).toEqual([
    "Fictional 1",
    "Fictional 2",
    "Fictional 3",
    "Fictional 4",
    "Fictional 5",
    "Fictional 6",
    "Show all leads",
  ]);
  expect(found[0].aside?.label).toBe("Call Fictional 1, ends in 3210");
  expect(found[1].aside).toBeUndefined();
  found[0].aside?.run();
  expect(act.call).toHaveBeenCalledWith(leads[0]);
  found[0].run();
  expect(act.open).toHaveBeenCalledWith("lead-1");
  found.at(-1)?.run();
  expect(act.showAll).toHaveBeenCalledWith("fic");
  // Six or fewer: no Show all.
  expect(
    leadSearchCommands([row(1)], "fi", act).map((item) => item.id),
  ).toEqual(["leads:open:lead-1"]);
});

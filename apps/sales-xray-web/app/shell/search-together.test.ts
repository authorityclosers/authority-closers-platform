import { expect, it } from "vitest";

import { searchTogether } from "./search-together";

it("asks for leads and the other searches together, not one after another", async () => {
  // Redmi QA on production (10 Nov 2026): search said "Looking for leads and
  // calls..." for 3-4 s while each server query took a few ms.
  const started: string[] = [];
  let finishLeads: (value: string[]) => void = () => {};
  const leads = () => {
    started.push("leads");
    return new Promise<string[]>((resolve) => {
      finishLeads = resolve;
    });
  };
  const calls = async () => {
    started.push("calls");
    return ["call"];
  };
  const broken = async (): Promise<string[]> => {
    started.push("broken");
    throw new Error("down");
  };
  const both = searchTogether(leads, [calls, broken]);
  // Every search is out before the leads read has answered.
  expect(started).toEqual(["leads", "calls", "broken"]);
  finishLeads(["lead"]);
  expect(await both).toEqual([["lead"], ["call"]]);
  // A failed leads read adds nothing.
  expect(
    await searchTogether(async () => Promise.reject(new Error("x")), []),
  ).toEqual([[], []]);
});

import { expect, it } from "vitest";

import { firstCallGuideFits } from "../guide-host";

it("keeps the first-call guide off the CRM's pages (Leads, Chats)", () => {
  expect(firstCallGuideFits("/leads")).toBe(false);
  expect(firstCallGuideFits("/leads/")).toBe(false);
  expect(firstCallGuideFits("/chats")).toBe(false);
  expect(firstCallGuideFits("/organisation")).toBe(false);
  expect(firstCallGuideFits("/account")).toBe(false);
  // The call-analysis journey keeps it.
  expect(firstCallGuideFits("/analysis/new")).toBe(true);
  expect(firstCallGuideFits("/dashboard")).toBe(true);
  expect(firstCallGuideFits("/leadsboard")).toBe(true);
  expect(firstCallGuideFits(null)).toBe(true);
});

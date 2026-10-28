import { expect, it } from "vitest";
import { legacyLeadSettings } from "./legacy-settings";

it("takes old settings links to the gear's normal destinations, preserving connection replies", () => {
  expect(legacyLeadSettings("tab=team")).toBe("/settings/lead-rules");
  expect(legacyLeadSettings("tab=stages")).toBe("/settings/stages");
  expect(legacyLeadSettings("tab=sources&connected=meta")).toBe(
    "/settings/sources?connected=meta",
  );
  expect(legacyLeadSettings("tab=all&stage=new")).toBeNull();
  expect(legacyLeadSettings("tab=numbers")).toBeNull();
});

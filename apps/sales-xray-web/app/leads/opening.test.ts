import { expect, it } from "vitest";

import { listScope } from "./opening";

it("lists the team's leads for whoever sees the team, a seller's own otherwise", () => {
  expect(listScope({ can_manage: true })).toBe("team");
  // A Viewer changes nothing but reads every lead (owner, 2 Nov 2026).
  expect(listScope({ can_manage: false, can_see_team: true })).toBe("team");
  expect(listScope({ can_manage: false, can_see_team: false })).toBe("mine");
  expect(listScope({ can_manage: false })).toBe("mine");
});

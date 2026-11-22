// @vitest-environment happy-dom
import { beforeEach, expect, it } from "vitest";

import { forgetAccess, keptAccess, rememberAccess } from "./last-access";

// v1.96 device polish, lane P: on a 502 Leads swapped shells; the tab keeps
// the frame it last confirmed instead, and forgets it on sign-out.
beforeEach(() => sessionStorage.clear());

it("keeps the confirmed workspace for this tab, and forgets it", () => {
  expect(keptAccess()).toBeNull();
  rememberAccess({ selected_tenant_id: null, workspaces: [] });
  expect(keptAccess()).toBeNull();
  const choices = {
    selected_tenant_id: "t1",
    workspaces: [{ tenant_id: "t1" }],
  };
  rememberAccess(choices);
  expect(keptAccess()).toEqual(choices);
  forgetAccess();
  expect(keptAccess()).toBeNull();
  sessionStorage.setItem("sx.last-access", "{not json");
  expect(keptAccess()).toBeNull();
});

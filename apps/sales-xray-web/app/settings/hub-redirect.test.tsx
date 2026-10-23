import { expect, it } from "vitest";

import { hubTarget } from "./hub-redirect";

// Owner, 23 Oct 2026: the organisation's settings live in its hub; an old
// address (a saved link, a connect flow coming back) keeps its own query.
it("goes to the hub's tab with the old address's own query kept", () => {
  expect(hubTarget("/organisation?tab=team", "")).toBe(
    "/organisation?tab=team",
  );
  expect(
    hubTarget(
      "/organisation?tab=connections&part=apps",
      "?connected=meta&page=123",
      "#whatsapp",
    ),
  ).toBe(
    "/organisation?tab=connections&part=apps&connected=meta&page=123#whatsapp",
  );
  // The hub decides its own tab and part.
  expect(
    hubTarget("/organisation?tab=leads&part=stages", "?tab=x&part=y&q=1"),
  ).toBe("/organisation?tab=leads&part=stages&q=1");
});

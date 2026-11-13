import { expect, it } from "vitest";

import { notLoadedText } from "./work-views";

// Redmi QA (10 Nov 2026): offline, Leads said "Sales X-Ray isn't answering.
// Try again." and never that the phone was offline; it now says so, and that
// the list comes back by itself (Leads reads again once the phone is online).
it("says the phone is offline when it is, and the server's words otherwise", () => {
  expect(notLoadedText("Sales X-Ray isn't answering. Try again.", false)).toBe(
    "You're offline. They load by themselves once you're back online.",
  );
  expect(notLoadedText("Sales X-Ray isn't answering. Try again.", true)).toBe(
    "Sales X-Ray isn't answering. Try again.",
  );
});

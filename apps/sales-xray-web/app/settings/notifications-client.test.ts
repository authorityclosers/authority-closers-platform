import { expect, it } from "vitest";

import { noPhoneWords } from "./notifications-client";

// Phone personas ph1-57 (1 Nov 2026): inside the phone app, the alerts page
// told its owner to "sign in to the app on your phone".
it("inside the phone app, points at this phone's notifications, never at signing in", () => {
  expect(noPhoneWords(true)).toBe(
    "This phone isn't getting alerts yet. Allow notifications for Sales X-Ray on it, then try again.",
  );
  expect(noPhoneWords(true)).not.toMatch(/sign in/i);
  expect(noPhoneWords(false)).toBe(
    "Alerts reach the Sales X-Ray app. Sign in to it on your phone to get them.",
  );
});

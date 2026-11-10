import { afterEach, expect, it } from "vitest";

import {
  forgetAppCall,
  questionPlace,
  rememberAppCall,
  takeAppCall,
} from "./lead-sheet";

afterEach(() => window.localStorage.clear());

// Redmi QA C3 (10 Nov 2026): Log a call, tapped lower down, opened the
// question above the screen and nothing seemed to happen. It scrolls into view
// from above as well as from below; in sight, it stays where it is.
it("brings the call's question into view from below or above", () => {
  expect(questionPlace(600, 735)).toBe("center");
  expect(questionPlace(-240, 735)).toBe("start");
  expect(questionPlace(30, 735)).toBe("start");
  expect(questionPlace(200, 735)).toBeNull();
  // In sight, but its answers under the Call and the tab bar: up to the top.
  expect(questionPlace(200, 735, 64, 690)).toBe("start");
  expect(questionPlace(200, 735, 64, 560)).toBeNull();
});

// Redmi QA C2 (10 Nov 2026): back from a call the phone app placed, nothing
// showed when the phone couldn't say how the call ended. The page remembers
// the call it placed and says it once, after 4 s away and within 30 minutes.
it("remembers the app's call for its lead, once, after four seconds away", () => {
  const at = Date.parse("2026-11-10T09:00:00Z");
  rememberAppCall("lead-1", at);
  expect(takeAppCall("lead-1", at + 2_000)).toBeNull();
  expect(takeAppCall("lead-2", at + 10_000)).toBeNull();
  expect(takeAppCall("lead-1", at + 10_000)).toEqual({
    leadId: "lead-1",
    at,
  });
  expect(takeAppCall("lead-1", at + 12_000)).toBeNull();
});

it("forgets the app's call when the phone says how it ended, or when it is old", () => {
  const at = Date.parse("2026-11-10T09:00:00Z");
  rememberAppCall("lead-1", at);
  forgetAppCall("lead-1");
  expect(takeAppCall("lead-1", at + 10_000)).toBeNull();
  rememberAppCall("lead-1", at);
  expect(takeAppCall("lead-1", at + 31 * 60 * 1000)).toBeNull();
});

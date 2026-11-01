// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";

import {
  PAUSE_KEEP_MS,
  keepPaused,
  nextInRound,
  readPaused,
  roundDone,
  triedLately,
} from "./call-round";

afterEach(() => window.sessionStorage.clear());

// Competitor teardown 2 (1 Nov 2026): Skip sends a lead to the end of the
// round, a new enquiry comes first, Continue passes over leads just tried.
it("goes through the list, a new enquiry first, then the skipped at the end", () => {
  const order = ["a", "b", "c"];
  expect(nextInRound({ order, served: new Set(), skipped: [] }).next).toBe("a");
  expect(
    nextInRound({ ahead: ["n"], order, served: new Set(["a"]), skipped: [] })
      .next,
  ).toBe("n");
  // b was skipped: c comes first, then b again.
  expect(
    nextInRound({ order, served: new Set(["a", "b"]), skipped: ["b"] }).next,
  ).toBe("c");
  expect(
    nextInRound({ order, served: new Set(["a", "b", "c"]), skipped: ["b"] }),
  ).toEqual({ next: "b", again: true });
  expect(
    nextInRound({ order, served: new Set(order), skipped: [] }).next,
  ).toBeNull();
  // Continue: b was tried in the last hour elsewhere.
  expect(
    nextInRound({
      order,
      served: new Set(["a"]),
      skipped: [],
      recent: new Set(["b"]),
    }).next,
  ).toBe("c");
});

it("says what the round did from the desk's numbers", () => {
  expect(
    roundDone(
      { calls: 4, connected: 1, talk_seconds: 60 },
      { calls: 13, connected: 5, talk_seconds: 1140 },
    ),
  ).toEqual({ tried: 9, talked: 4, minutes: 18 });
  expect(roundDone(null, { calls: 1, connected: 0, talk_seconds: 0 })).toBe(
    null,
  );
});

it("keeps a paused round for its side for half a day", () => {
  const at = Date.parse("2026-11-01T10:00:00Z");
  keepPaused("me", {
    side: "cold",
    served: ["a", "b"],
    skipped: ["b"],
    at,
    start: null,
  });
  expect(readPaused("me", "cold", at + 60_000)?.served).toEqual(["a", "b"]);
  expect(readPaused("me", "inbound", at)).toBeNull();
  expect(readPaused("me", "cold", at + PAUSE_KEEP_MS + 1)).toBeNull();
  keepPaused("me", null);
  expect(readPaused("me", "cold", at)).toBeNull();
});

it("finds the leads tried in the last hour", () => {
  const now = Date.parse("2026-11-01T10:00:00Z");
  expect(
    triedLately(
      [
        { lead_id: "a", last_contact_at: "2026-11-01T09:30:00Z" },
        { lead_id: "b", last_contact_at: "2026-11-01T08:30:00Z" },
        { lead_id: "c", last_contact_at: null },
      ],
      now,
    ),
  ).toEqual(["a"]);
});

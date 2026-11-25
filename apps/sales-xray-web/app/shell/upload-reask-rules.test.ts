import { beforeEach, expect, it } from "vitest";

import type { MissingCall } from "../capture-setup/capture-setup-client";
import {
  headline,
  markShown,
  readShown,
  uncheckedCall,
  uploadStepsLeft,
  uploadsOffHere,
} from "./upload-reask-rules";

const NOW = Date.parse("2026-11-18T10:30:00Z");

function call(over: Partial<MissingCall> = {}): MissingCall {
  return {
    event_id: "call-1",
    lead_id: "lead-fictional-1",
    lead_name: "Asha Patil",
    // 3:40 PM India time, a 2-minute call, ended 18 minutes before NOW.
    at: "2026-11-18T10:10:00Z",
    seconds: 120,
    ...over,
  };
}

beforeEach(() => window.localStorage.clear());

it("names the call ten minutes after it ended, and covers every call that waits", () => {
  const found = uncheckedCall(
    [call(), call({ event_id: "call-0", at: "2026-11-18T09:00:00Z" })],
    NOW,
    new Set(),
  );
  expect(found).toMatchObject({
    eventId: "call-1",
    clock: "3:40 PM",
    detail: "2 min call · 3:40 PM",
    href: "/leads?lead=lead-fictional-1",
    callIds: ["call-1", "call-0"],
  });
  expect(found && headline(found)).toBe(
    "Your call with Asha Patil at 3:40 PM wasn't checked",
  );
});

it("waits ten minutes after the call ends, skips calls already shown and day-old calls", () => {
  // Ended 8 minutes ago: an upload may still come.
  expect(
    uncheckedCall([call({ at: "2026-11-18T10:20:00Z" })], NOW, new Set()),
  ).toBeNull();
  expect(uncheckedCall([call()], NOW, new Set(["call-1"]))).toBeNull();
  expect(
    uncheckedCall([call({ at: "2026-11-17T09:00:00Z" })], NOW, new Set()),
  ).toBeNull();
  expect(uncheckedCall([call({ lead_name: null })], NOW, new Set())?.name).toBe(
    "your lead",
  );
});

it("only a phone that says uploads are off counts; a late answer doesn't", () => {
  expect(uploadsOffHere({ supported: true, on: false, wifiOnly: false })).toBe(
    true,
  );
  expect(uploadsOffHere({ supported: true, on: true, wifiOnly: false })).toBe(
    false,
  );
  expect(
    uploadsOffHere({
      supported: true,
      on: false,
      wifiOnly: true,
      unanswered: true,
    }),
  ).toBe(false);
  expect(uploadsOffHere(null)).toBe(false);
});

it("asks only what is missing, uploads last", () => {
  expect(
    uploadStepsLeft({ notifications: false, folderPicked: false }),
  ).toEqual(["notices", "folder", "uploads"]);
  expect(uploadStepsLeft({ notifications: true, folderPicked: true })).toEqual([
    "uploads",
  ]);
});

it("remembers every call it was shown for on this phone", () => {
  markShown("acct", ["a", "b"]);
  markShown("acct", ["b", "c"]);
  expect([...readShown("acct")]).toEqual(["a", "b", "c"]);
  expect(readShown("other").size).toBe(0);
});

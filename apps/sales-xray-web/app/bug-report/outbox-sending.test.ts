import { afterEach, expect, it, vi } from "vitest";

import {
  holdState,
  holdingFetch,
  resetHold,
  type HoldDeps,
} from "../release-hold";
import {
  BugReportError,
  postBugReportNow,
  savedWords,
} from "./bug-report-client";
import { RETRY_MS, keepSending } from "./outbox";

// Phone personas ph1-44 and ph1-45 (1 Nov 2026), during a staging release:
// Sending… spun for two minutes, then blamed the connection of a phone that
// was online, and the saved reports went only after the app was reopened.

const ORIGIN = window.location.origin;
const hold = () =>
  new Response("Updating.", {
    status: 503,
    headers: {
      "content-type": "text/plain",
      "retry-after": "30",
      "x-authority-closers-route": "release-hold-production",
    },
  });
const deps: HoldDeps = {
  sleep: async () => {},
  now: () => 0,
  byPerson: () => false,
  origin: () => ORIGIN,
};
/** Sales X-Ray updating: the edge's hold answered once. */
async function updating() {
  await holdingFetch(async () => hold(), deps)("/v1/probe", {
    method: "POST",
    body: "{}",
  });
  expect(holdState().holding).toBe(true);
}

afterEach(() => {
  resetHold();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("sends what waits now, back online, when an update ends, and each minute while any wait", async () => {
  vi.useFakeTimers();
  const send = vi.fn(async () => 1);
  const stop = keepSending(send);
  await vi.advanceTimersByTimeAsync(0);
  expect(send).toHaveBeenCalledTimes(1);
  // Still waiting: tried again a minute later.
  await vi.advanceTimersByTimeAsync(RETRY_MS);
  expect(send).toHaveBeenCalledTimes(2);
  window.dispatchEvent(new Event("online"));
  await vi.advanceTimersByTimeAsync(0);
  expect(send).toHaveBeenCalledTimes(3);
  // An update ends (no `online` event, no reload): it goes then.
  await updating();
  resetHold();
  await vi.advanceTimersByTimeAsync(0);
  expect(send).toHaveBeenCalledTimes(4);
  // Nothing left: no more tries.
  send.mockResolvedValue(0);
  await vi.advanceTimersByTimeAsync(RETRY_MS);
  expect(send).toHaveBeenCalledTimes(5);
  await vi.advanceTimersByTimeAsync(RETRY_MS * 3);
  expect(send).toHaveBeenCalledTimes(5);
  stop();
});

it("never sends into an update: it answers at once, and says it's an update", async () => {
  const fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetcher);
  await updating();
  const refused = await postBugReportNow({ words: "Fictional" }).catch(
    (error: unknown) => error,
  );
  expect(refused).toBeInstanceOf(BugReportError);
  expect((refused as BugReportError).status).toBe(503);
  expect(fetcher).not.toHaveBeenCalled();
  expect(savedWords(refused)).toBe(
    "Sales X-Ray is updating. It goes by itself as soon as it's back.",
  );
});

it("names the reason a report waits, never blaming an online phone", () => {
  const unreachable = new BugReportError("No answer.", 0);
  expect(savedWords(unreachable)).toBe(
    "Sales X-Ray didn't answer. It goes by itself as soon as it does.",
  );
  vi.stubGlobal("navigator", { ...navigator, onLine: false });
  expect(savedWords(unreachable)).toBe(
    "It goes by itself as soon as you're back online.",
  );
});

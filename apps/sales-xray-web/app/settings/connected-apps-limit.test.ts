import { afterEach, expect, it, vi } from "vitest";

import { limited } from "./connected-apps-client";

afterEach(() => {
  vi.useRealTimers();
});

// Bug report #14 (25 Oct 2026): "this loading takes forever".
it("gives a request up after the time limit, or when the caller stops it", () => {
  vi.useFakeTimers();
  const own = limited(undefined, 1000);
  expect(own.aborted).toBe(false);
  vi.advanceTimersByTime(1000);
  expect(own.aborted).toBe(true);

  const caller = new AbortController();
  const linked = limited(caller.signal, 1000);
  caller.abort();
  expect(linked.aborted).toBe(true);

  const gone = new AbortController();
  gone.abort();
  expect(limited(gone.signal, 1000).aborted).toBe(true);
});

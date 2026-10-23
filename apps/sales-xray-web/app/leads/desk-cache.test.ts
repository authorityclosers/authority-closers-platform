import { afterEach, expect, it, vi } from "vitest";

import { forgetCalls, identityOf } from "../calls-cache";
import { EARLY_CONVERSATION_KEY, startEarlyReads } from "../early-reads";
import { cachedDesk, rememberDesk } from "./desk-cache";
import { readDesk, type Desk } from "./leads-client";

const me = identityOf({ personId: "p1", sessionId: "s1", tenantId: "t1" });
const desk = {
  queue: [],
  call_back: [],
  me: { person_id: "p1", can_manage: false },
  counts: { open: 4, overdue: 1 },
  numbers: { calls: 2 },
} as unknown as Desk;

afterEach(() => {
  forgetCalls();
  delete (window as Window & { __sxEarly?: unknown }).__sxEarly;
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

it("paints a return to Leads from this identity's last desk, per pipeline", () => {
  expect(cachedDesk(me, null)).toBeNull();
  rememberDesk(me, null, desk);
  expect(cachedDesk(me, null)).toBe(desk);
  // Another pipeline, another session or no identity: nothing to paint.
  expect(cachedDesk(me, "rentals")).toBeNull();
  expect(
    cachedDesk(
      identityOf({ personId: "p1", sessionId: "s2", tenantId: "t1" }),
      null,
    ),
  ).toBeNull();
  expect(cachedDesk(null, null)).toBeNull();
  rememberDesk(null, null, desk);
  expect(cachedDesk(null, null)).toBeNull();
});

it("takes the desk read the Leads tab press started instead of asking again", async () => {
  window.sessionStorage.setItem(EARLY_CONVERSATION_KEY, "1");
  const network = vi.fn<typeof fetch>(
    async () =>
      new Response(JSON.stringify(desk), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", network);
  startEarlyReads("/leads");
  expect(network).toHaveBeenCalledTimes(1);
  expect(network.mock.calls[0]?.[0]).toBe("/v1/lead-desk");
  const read = await readDesk();
  expect(read.counts.open).toBe(4);
  expect(network).toHaveBeenCalledTimes(1);
});

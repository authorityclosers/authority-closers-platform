import { afterEach, describe, expect, it } from "vitest";

import {
  HOLD_WAIT_MS,
  dropKept,
  holdDelay,
  holdState,
  holdingFetch,
  isReleaseHold,
  resetHold,
  retrySafe,
  sendKept,
  type HoldDeps,
} from "./release-hold";

const ORIGIN = "https://salesxray.example.test";

function hold(extra: Record<string, string> = {}): Response {
  return new Response(
    "Authority Closers production is completing a reviewed release.",
    {
      status: 503,
      headers: {
        "content-type": "text/plain",
        "retry-after": "30",
        "x-authority-closers-route": "release-hold-production",
        ...extra,
      },
    },
  );
}

const ok = () => Response.json({ ok: true });
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

/** A fetch that answers from a list, and remembers what it was asked. */
function scripted(answers: (() => Response)[]) {
  const seen: { url: string; method: string; body: unknown }[] = [];
  const base = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({
      url: String(input instanceof Request ? input.url : input),
      method: init?.method ?? "GET",
      body: init?.body,
    });
    const next = answers.shift();
    if (!next) throw new Error("no answer left");
    return next();
  }) as typeof fetch;
  return { base, seen };
}

/** No real waiting: the clock moves by each wait. */
function deps(byPerson = true): HoldDeps & { waited: number[] } {
  let clock = 0;
  const waited: number[] = [];
  return {
    waited,
    sleep: async (ms, signal) => {
      if (signal?.aborted) throw new DOMException("x", "AbortError");
      waited.push(ms);
      clock += ms;
    },
    now: () => clock,
    byPerson: () => byPerson,
    origin: () => ORIGIN,
  };
}

afterEach(() => resetHold());

describe("the release hold detector", () => {
  it("knows the edge's hold by its route header, or a plain 503 with Retry-After", () => {
    expect(isReleaseHold(hold())).toBe(true);
    expect(isReleaseHold(hold({ "x-authority-closers-route": "" }))).toBe(true);
    const json503 = Response.json(
      { detail: "New analysis is temporarily paused." },
      { status: 503 },
    );
    expect(isReleaseHold(json503)).toBe(false);
    expect(
      isReleaseHold(
        new Response("busy", {
          status: 503,
          headers: { "content-type": "text/plain" },
        }),
      ),
    ).toBe(false);
    expect(isReleaseHold(new Response("x", { status: 502 }))).toBe(false);
    expect(isReleaseHold(ok())).toBe(false);
  });
});

describe("the retry policy", () => {
  it("waits 2, 4, 8, then 15 seconds", () => {
    expect([0, 1, 2, 3, 4, 9].map(holdDelay)).toEqual([
      2_000, 4_000, 8_000, 15_000, 15_000, 15_000,
    ]);
  });

  it("sends reads and keyed writes again, never other writes on its own", () => {
    const none = new Headers();
    expect(retrySafe("GET", none, undefined)).toBe(true);
    expect(retrySafe("put", none, "x")).toBe(true);
    expect(
      retrySafe("POST", new Headers({ "Idempotency-Key": "k1" }), "{}"),
    ).toBe(true);
    expect(retrySafe("POST", none, JSON.stringify({ command_id: "c1" }))).toBe(
      true,
    );
    expect(retrySafe("PATCH", none, JSON.stringify({ request_id: "r1" }))).toBe(
      true,
    );
    expect(retrySafe("POST", none, JSON.stringify({ note: "hi" }))).toBe(false);
    expect(retrySafe("POST", none, JSON.stringify({ command_id: "" }))).toBe(
      false,
    );
    expect(retrySafe("POST", none, "not json")).toBe(false);
    expect(retrySafe("POST", none, new FormData())).toBe(false);
  });
});

describe("the fetch layer", () => {
  it("waits a read through the release, then clears the banner", async () => {
    const { base, seen } = scripted([hold, hold, ok]);
    const clock = deps();
    const answer = holdingFetch(base, clock)("/v1/context");
    const response = await answer;
    expect(response.status).toBe(200);
    expect(seen).toHaveLength(3);
    expect(clock.waited).toEqual([2_000, 4_000]);
    expect(holdState()).toEqual({ holding: false, kept: 0 });
  });

  it("gives up after about 3 minutes and hands back the hold", async () => {
    const { base, seen } = scripted(Array.from({ length: 40 }, () => hold));
    const clock = deps();
    const response = await holdingFetch(base, clock)("/v1/leads");
    expect(response.status).toBe(503);
    const total = clock.waited.reduce((sum, ms) => sum + ms, 0);
    expect(total).toBeLessThanOrEqual(HOLD_WAIT_MS);
    expect(total).toBeGreaterThan(HOLD_WAIT_MS - 15_000);
    expect(seen.length).toBe(clock.waited.length + 1);
    expect(holdState().holding).toBe(true);
  });

  it("sends a keyed write again with the same body", async () => {
    const body = JSON.stringify({ command_id: "c-1", note: "Wants a demo" });
    const { base, seen } = scripted([hold, ok]);
    const response = await holdingFetch(base, deps())("/v1/leads/l1/notes", {
      method: "POST",
      body,
    });
    expect(response.status).toBe(200);
    expect(seen.map((call) => call.body)).toEqual([body, body]);
  });

  it("keeps a person's unkeyed write until Retry, then sends it once", async () => {
    const { base, seen } = scripted([hold, ok]);
    const pending = holdingFetch(base, deps())("/v1/me/profile", {
      method: "POST",
      body: JSON.stringify({ name: "Asha" }),
    });
    await flush();
    expect(holdState()).toEqual({ holding: true, kept: 1 });
    expect(seen).toHaveLength(1);
    sendKept();
    expect((await pending).status).toBe(200);
    expect(seen).toHaveLength(2);
    expect(holdState()).toEqual({ holding: false, kept: 0 });
  });

  it("Not now hands the caller the answer it would have had", async () => {
    const { base } = scripted([hold]);
    const pending = holdingFetch(base, deps())("/v1/me/profile", {
      method: "POST",
      body: "{}",
    });
    await flush();
    dropKept();
    expect((await pending).status).toBe(503);
    expect(holdState().kept).toBe(0);
  });

  it("leaves background and other sites' requests alone", async () => {
    const telemetry = scripted([hold]);
    const sent = await holdingFetch(telemetry.base, deps())(
      "/v1/telemetry/events",
      { method: "POST", body: "{}" },
    );
    expect(sent.status).toBe(503);
    const unprompted = scripted([hold]);
    expect(
      (
        await holdingFetch(unprompted.base, deps(false))("/v1/me/profile", {
          method: "POST",
          body: "{}",
        })
      ).status,
    ).toBe(503);
    expect(holdState().kept).toBe(0);
    const elsewhere = scripted([hold]);
    expect(
      (await holdingFetch(elsewhere.base, deps())("https://storage.example/x"))
        .status,
    ).toBe(503);
    expect(elsewhere.seen).toHaveLength(1);
  });

  it("stops waiting when the caller cancels", async () => {
    const { base } = scripted([hold, ok]);
    const controller = new AbortController();
    controller.abort();
    await expect(
      holdingFetch(base, deps())("/v1/context", { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

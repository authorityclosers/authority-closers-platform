import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchProspectDetail,
  fetchProspectsList,
  PROSPECT_READ_TIMEOUT_MS,
} from "./prospects-client";
import { syntheticProspect } from "./review-fixture/prospects/synthetic-prospect";

const DEADLINE = PROSPECT_READ_TIMEOUT_MS;
const UNAVAILABLE = "Prospect information is unavailable. Try again.";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe.each(["list", "profile"] as const)(
  "Prospect %s read recovery",
  (page) => {
    const payload =
      page === "list"
        ? {
            schema: "ac.sales-xray.prospects/1",
            prospects: [syntheticProspect],
            total: 1,
            stage_filters: [],
            next_offset: null,
          }
        : {
            schema: "ac.sales-xray.prospects/1",
            prospect: syntheticProspect,
            calls: [],
            next_offset: null,
            promises: [],
            next_steps: [],
            buyer_intent_history: [],
          };
    const read = (signal?: AbortSignal) =>
      page === "list"
        ? fetchProspectsList({ signal })
        : fetchProspectDetail({
            prospectId: syntheticProspect.prospect_id,
            signal,
          });

    it.each(["headers", "success body", "error body"] as const)(
      "finishes a stalled %s at the deadline and discards its late result",
      async (phase) => {
        const pendingHeaders = deferred<Response>();
        const pendingBody = deferred<unknown>();
        const response = {
          ok: phase !== "error body",
          status: phase === "error body" ? 503 : 200,
          json: () => pendingBody.promise,
        } as Response;
        let requestSignal: AbortSignal | undefined;
        const fetch = vi.fn((_url: string, init: RequestInit) => {
          requestSignal = init.signal as AbortSignal;
          return phase === "headers"
            ? pendingHeaders.promise
            : Promise.resolve(response);
        });
        vi.stubGlobal("fetch", fetch);
        let settled: unknown = "pending";
        const completed = read().then(
          (value) => {
            settled = value;
          },
          (error: unknown) => {
            settled = error;
          },
        );
        await vi.advanceTimersByTimeAsync(DEADLINE - 1);
        expect(settled).toBe("pending");
        await vi.advanceTimersByTimeAsync(1);
        expect(settled).toBeInstanceOf(Error);
        expect((settled as Error).message).toBe(UNAVAILABLE);
        expect(requestSignal?.aborted).toBe(true);
        expect(fetch).toHaveBeenCalledOnce();
        expect(vi.getTimerCount()).toBe(0);
        pendingBody.resolve(payload);
        pendingHeaders.resolve(new Response(JSON.stringify(payload)));
        await completed;
        expect((settled as Error).message).toBe(UNAVAILABLE);
      },
    );

    it("cancels an uncooperative read on scope loss without waiting for the deadline", async () => {
      const controller = new AbortController();
      const fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
      vi.stubGlobal("fetch", fetch);
      const failure = read(controller.signal).catch((error: unknown) => error);
      controller.abort();
      expect(await failure).toBeInstanceOf(Error);
      expect((fetch.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("uses one deadline across headers and body rather than granting a second wait", async () => {
      const headers = deferred<Response>();
      const body = deferred<unknown>();
      vi.stubGlobal("fetch", vi.fn().mockReturnValue(headers.promise));
      let settled: unknown = "pending";
      const completed = read().catch((error: unknown) => {
        settled = error;
      });
      await vi.advanceTimersByTimeAsync(DEADLINE - 1);
      headers.resolve({
        ok: true,
        status: 200,
        json: () => body.promise,
      } as Response);
      await vi.advanceTimersByTimeAsync(1);
      expect(settled).toBeInstanceOf(Error);
      expect((settled as Error).message).toBe(UNAVAILABLE);
      body.resolve(payload);
      await completed;
      expect(vi.getTimerCount()).toBe(0);
    });

    it("does not send a private GET for a scope that is already cancelled", async () => {
      const controller = new AbortController();
      controller.abort();
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify(payload)));
      vi.stubGlobal("fetch", fetch);
      await expect(read(controller.signal)).rejects.toThrow(UNAVAILABLE);
      expect(fetch).not.toHaveBeenCalled();
      expect(vi.getTimerCount()).toBe(0);
    });

    it("cleans up a successful read without aborting the caller or retaining its listener", async () => {
      const controller = new AbortController();
      const remove = vi.spyOn(controller.signal, "removeEventListener");
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify(payload)));
      vi.stubGlobal("fetch", fetch);
      const value = await read(controller.signal);
      expect(value).toMatchObject({ schema: "ac.sales-xray.prospects/1" });
      expect(controller.signal.aborted).toBe(false);
      expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
      expect(vi.getTimerCount()).toBe(0);
      expect(fetch.mock.calls[0][1]).toMatchObject({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
    });
  },
);

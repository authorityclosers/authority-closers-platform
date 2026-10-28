import { afterEach, expect, it, vi } from "vitest";
import { metaRequest, refreshForms } from "./meta-client";
import type { MetaPage } from "../../leads/sources-view";
afterEach(() => vi.unstubAllGlobals());
it("refreshes every account's forms and isolates a refused Page", async () => {
  const fetcher = vi.fn(async (url: string) =>
    url.includes("bad")
      ? new Response("{}", { status: 403 })
      : Response.json([
          {
            id: url.includes("second") ? "archived" : "fresh",
            name: "Sample form",
            status: "ARCHIVED",
          },
        ]),
  );
  vi.stubGlobal("fetch", fetcher);
  const take = vi.fn();
  await refreshForms(
    ["first", "bad", "second"].map((pageId) => ({ pageId }) as MetaPage),
    take,
    new AbortController().signal,
  );
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(take).toHaveBeenCalledWith("bad", null);
  expect(take).toHaveBeenCalledWith("second", [
    expect.objectContaining({ id: "archived" }),
  ]);
});
it("bounds concurrent catalogue reads and does not continue after leaving", async () => {
  const control = new AbortController();
  let active = 0,
    peak = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      active++;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      active--;
      return Response.json([]);
    }),
  );
  await refreshForms(
    Array.from({ length: 8 }, (_, at) => ({ pageId: String(at) }) as MetaPage),
    vi.fn(),
    control.signal,
  );
  expect(peak).toBe(3);
  control.abort();
  const take = vi.fn();
  await refreshForms(
    [{ pageId: "unused" }] as MetaPage[],
    take,
    control.signal,
  );
  expect(take).not.toHaveBeenCalled();
});
it("sends explicit selected archived forms without retrying a write", async () => {
  const fetcher = vi.fn(async () => Response.json({ page: {} }));
  vi.stubGlobal("fetch", fetcher);
  await metaRequest("/pages/sample/backfill", { forms: ["old-form"] });
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0]).toEqual([
    "/v1/lead-desk/meta/pages/sample/backfill",
    expect.objectContaining({
      method: "POST",
      body: '{"forms":["old-form"]}',
      signal: undefined,
    }),
  ]);
});

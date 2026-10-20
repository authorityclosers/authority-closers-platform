import { afterEach, expect, it, vi } from "vitest";

import { EARLY_CONVERSATION_KEY } from "../early-reads";
import { PREFETCH_PLACES, prefetchPlace } from "./route-prefetch";

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
  delete (window as { __sxEarly?: unknown }).__sxEarly;
});

it("prefetches the tab places, the busiest first", () => {
  expect(PREFETCH_PLACES).toEqual([
    "/leads",
    "/analysis/calls",
    "/dashboard",
    "/chats",
    "/analysis/new",
    "/prospects",
    "/coaching",
  ]);
});

it("asks for a place once while Next still holds it, and never the page on screen", () => {
  const router = { prefetch: vi.fn() };
  prefetchPlace(router, "/prospects?x=1");
  prefetchPlace(router, "/prospects?x=1");
  expect(router.prefetch).toHaveBeenCalledOnce();
  prefetchPlace(router, window.location.pathname);
  prefetchPlace(router, "https://example.com/elsewhere");
  prefetchPlace(router, "//example.com/elsewhere");
  expect(router.prefetch).toHaveBeenCalledOnce();
});

it("starts a pressed tab's first reads, never the session's again", () => {
  window.sessionStorage.setItem(EARLY_CONVERSATION_KEY, "1");
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("{}", { status: 200 }));
  prefetchPlace({ prefetch: vi.fn() }, "/analysis/calls", true);
  const urls = fetch.mock.calls.map(([url]) => String(url));
  expect(urls).toEqual([
    "/v1/conversation/acquisition/submissions?include_owners=true&order=reports_first&include_summary=true",
  ]);
  // Pressed again at once: the answer on its way is used.
  prefetchPlace({ prefetch: vi.fn() }, "/analysis/calls", true);
  expect(fetch).toHaveBeenCalledOnce();
});

it("starts no reads before this tab has seen Sales Xray on", () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  prefetchPlace({ prefetch: vi.fn() }, "/dashboard", true);
  expect(fetch).not.toHaveBeenCalled();
});

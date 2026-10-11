import { afterEach, describe, expect, it, vi } from "vitest";
import { loadServerCoaching } from "./coaching-server";
import Page from "./page";
import { fictionalCallCoaching } from "./coaching.fixture";

const mocks = vi.hoisted(() => ({ headers: vi.fn() }));
vi.mock("next/headers", () => ({ headers: mocks.headers }));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
describe("server coaching page", () => {
  it("loads the whole call result in one private fixed-origin request", async () => {
    vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "http://api.example.test:8000");
    mocks.headers.mockResolvedValue(
      new Headers({
        host: "sales-xray.example.test",
        cookie: "fictional-session=value",
      }),
    );
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fictionalCallCoaching), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const result = await loadServerCoaching(
      fictionalCallCoaching.submission_id,
    );
    expect(result?.data?.person_id).toBe(fictionalCallCoaching.person_id);
    expect(fetch).toHaveBeenCalledOnce();
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe(
      `http://api.example.test:8000/v1/me/coaching/calls/${fictionalCallCoaching.submission_id}`,
    );
    expect(options.cache).toBe("no-store");
    expect(options.headers.get("Host")).toBe("sales-xray.example.test");
    expect(options.headers.get("Cookie")).toBe("fictional-session=value");
  });
  it("static preview never reads request headers or awaited query data", async () => {
    vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "1");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await Page({ searchParams: new Promise(() => {}) });
    expect(mocks.headers).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("rejects invalid deployment origins and degrades network errors without diagnostics", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("private diagnostic"));
    vi.stubGlobal("fetch", fetch);
    for (const origin of [
      "https://api.example.test/path",
      "https://api.example.test?bad=1",
      "file:///tmp/data",
    ]) {
      vi.stubEnv("AC_CONVERSATION_API_ORIGIN", origin);
      expect((await loadServerCoaching(null))?.error).toContain("unavailable");
    }
    expect(fetch).not.toHaveBeenCalled();
    vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "https://api.example.test");
    mocks.headers.mockResolvedValue(
      new Headers({ host: "sales-xray.example.test" }),
    );
    expect(await loadServerCoaching(null)).toEqual({
      data: null,
      error: "Coaching could not be loaded. Try again.",
    });
  });
});

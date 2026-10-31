import { afterEach, describe, expect, it, vi } from "vitest";
import { loadServerCoaching } from "./coaching-server";
import Page from "./page";
import { fictionalCallCoaching } from "./coaching.fixture";

const mocks = vi.hoisted(() => ({ headers: vi.fn(), serverGet: vi.fn() }));
vi.mock("next/headers", () => ({ headers: mocks.headers }));
vi.mock("../server-get", () => ({ serverGet: mocks.serverGet }));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});
const answer = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  text: JSON.stringify(body),
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
    mocks.serverGet.mockResolvedValue(answer(fictionalCallCoaching));
    const result = await loadServerCoaching(
      fictionalCallCoaching.submission_id,
    );
    expect(result?.data?.person_id).toBe(fictionalCallCoaching.person_id);
    expect(mocks.serverGet).toHaveBeenCalledOnce();
    const [url, sent, signal] = mocks.serverGet.mock.calls[0];
    expect(url).toBe(
      `http://api.example.test:8000/v1/me/coaching/calls/${fictionalCallCoaching.submission_id}`,
    );
    // The page's own host, as the API expects (not the API's address).
    expect(sent.host).toBe("sales-xray.example.test");
    expect(sent.cookie).toBe("fictional-session=value");
    expect(signal).toBeInstanceOf(AbortSignal);
  });
  it("static preview never reads request headers or awaited query data", async () => {
    vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "1");
    await Page({ searchParams: new Promise(() => {}) });
    expect(mocks.headers).not.toHaveBeenCalled();
    expect(mocks.serverGet).not.toHaveBeenCalled();
  });
  it("leaves the read to the browser when the server read cannot succeed", async () => {
    mocks.serverGet.mockRejectedValue(new Error("private diagnostic"));
    for (const origin of [
      "https://api.example.test/path",
      "https://api.example.test?bad=1",
      "file:///tmp/data",
    ]) {
      vi.stubEnv("AC_CONVERSATION_API_ORIGIN", origin);
      expect(await loadServerCoaching(null)).toBeNull();
    }
    expect(mocks.serverGet).not.toHaveBeenCalled();
    vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "https://api.example.test");
    // No session cookie, or an in-app navigation: the browser reads.
    mocks.headers.mockResolvedValue(
      new Headers({ host: "sales-xray.example.test" }),
    );
    expect(await loadServerCoaching(null)).toBeNull();
    mocks.headers.mockResolvedValue(
      new Headers({
        host: "sales-xray.example.test",
        cookie: "fictional-session=value",
        "sec-fetch-dest": "empty",
      }),
    );
    expect(await loadServerCoaching(null)).toBeNull();
    expect(mocks.serverGet).not.toHaveBeenCalled();
    mocks.headers.mockResolvedValue(
      new Headers({
        host: "sales-xray.example.test",
        cookie: "fictional-session=value",
      }),
    );
    // A failed read, or an older or misrouted API without the route.
    expect(await loadServerCoaching(null)).toBeNull();
    mocks.serverGet.mockResolvedValue(answer({}, 404));
    expect(
      await loadServerCoaching(fictionalCallCoaching.submission_id),
    ).toBeNull();
  });
});

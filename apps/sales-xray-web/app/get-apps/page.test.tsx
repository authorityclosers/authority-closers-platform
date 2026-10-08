import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { GetApps } from "./get-apps";
import Page from "./page";
import { readDownloads } from "./downloads";
import { sessionStatus } from "./session";

vi.mock("next/headers", () => ({ headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("not_found");
  }),
  redirect: vi.fn(() => {
    throw new Error("redirect");
  }),
}));
vi.mock("./session", () => ({ sessionStatus: vi.fn() }));
vi.mock("./downloads", () => ({ readDownloads: vi.fn() }));
afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

it("renders all five platforms, their empty states and a tester checklist", () => {
  const html = renderToStaticMarkup(<GetApps downloads={null} />);
  for (const label of [
    "Android",
    "iOS",
    "Windows",
    "Mac",
    "Chrome",
    "Tester checklist",
  ])
    expect(html).toContain(label);
  expect(html.match(/Not available yet/g)).toHaveLength(5);
  expect(html.match(/type="checkbox"/g)).toHaveLength(3);
});
it("shows the manifest's version and exact SHA-256 with a download link", () => {
  const sha256 = "a".repeat(64);
  const html = renderToStaticMarkup(
    <GetApps
      downloads={{
        version: "0.1.0",
        files: [{ name: "test.apk", platform: "android", size: 10, sha256 }],
      }}
    />,
  );
  expect(html).toContain("Version 0.1.0");
  expect(html).toContain(sha256);
  expect(html).toContain('href="/api/downloads/test.apk"');
  expect(html.match(/Not available yet/g)).toHaveLength(4);
});
it("redirects signed-out visitors without reading the manifest", async () => {
  vi.mocked(sessionStatus).mockResolvedValue(401);
  await expect(Page()).rejects.toThrow("redirect");
  expect(readDownloads).not.toHaveBeenCalled();
});
it("shows a retry message if the account check fails and loads only after sign-in", async () => {
  vi.mocked(sessionStatus).mockResolvedValue(503);
  expect(renderToStaticMarkup(await Page())).toContain(
    "We couldn’t check your account",
  );
  expect(readDownloads).not.toHaveBeenCalled();
  vi.mocked(sessionStatus).mockResolvedValue(200);
  vi.mocked(readDownloads).mockResolvedValue(null);
  expect(
    renderToStaticMarkup(await Page()).match(/Not available yet/g),
  ).toHaveLength(5);
});

it("omits the signed-in page from the static preview without reading a manifest", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "1");
  await expect(Page()).rejects.toThrow("not_found");
  expect(sessionStatus).not.toHaveBeenCalled();
  expect(readDownloads).not.toHaveBeenCalled();
});

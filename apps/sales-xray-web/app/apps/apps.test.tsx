import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AppsView } from "./apps-view";
import {
  ANDROID_APK_URL,
  formatSize,
  latestAndroidRelease,
  readRelease,
  UNKNOWN_RELEASE,
} from "./release";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SHA = "0d83526a89747b2571cc0c5d009c53c95c31d5ed9b384dcda9741f33c0f4d836";
// GitHub's /releases/latest answer for 0.3.35, trimmed.
const GITHUB = {
  tag_name: "sales-xray-android-latest",
  name: "Sales Xray for Android 0.3.35",
  prerelease: false,
  published_at: "2026-10-16T21:45:51Z",
  assets: [
    {
      name: "sales-xray-android.apk",
      size: 4099815,
      digest: `sha256:${SHA}`,
      updated_at: "2026-10-18T10:58:02Z",
    },
    { name: "SHA256SUMS.txt", size: 89, digest: "sha256:af32" },
  ],
};

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("reads version, size, SHA-256 and the APK's own date from the release", () => {
  expect(readRelease(GITHUB)).toEqual({
    url: ANDROID_APK_URL,
    version: "0.3.35",
    sizeBytes: 4099815,
    sha256: SHA,
    updatedAt: "2026-10-18T10:58:02Z",
  });
  expect(ANDROID_APK_URL).toBe(
    "https://github.com/authorityclosers/sales-xray-apps/releases/latest/download/sales-xray-android.apk",
  );
  expect(formatSize(4099815)).toBe("4.1 MB");
});

it("leaves out anything odd but keeps the download", () => {
  expect(readRelease(null)).toEqual(UNKNOWN_RELEASE);
  expect(readRelease({ assets: [{ name: "other.apk" }] })).toEqual(
    UNKNOWN_RELEASE,
  );
  const odd = readRelease({
    name: "no version",
    assets: [
      {
        name: "sales-xray-android.apk",
        size: -1,
        digest: "md5:x",
        updated_at: "soon",
      },
    ],
  });
  expect(odd).toEqual({ ...UNKNOWN_RELEASE });
  expect(odd.url).toBe(ANDROID_APK_URL);
});

it("falls back quietly when GitHub can't be reached", async () => {
  const down = vi.fn(async () => {
    throw new Error("offline");
  }) as unknown as typeof fetch;
  expect(await latestAndroidRelease(down)).toEqual(UNKNOWN_RELEASE);
  const limited = vi.fn(
    async () => new Response("{}", { status: 403 }),
  ) as unknown as typeof fetch;
  expect(await latestAndroidRelease(limited)).toEqual(UNKNOWN_RELEASE);
  const ok = vi.fn(async () =>
    Response.json(GITHUB),
  ) as unknown as typeof fetch;
  expect((await latestAndroidRelease(ok)).version).toBe("0.3.35");
});

it("offers one big Android download with a QR code, the file's facts and three steps", async () => {
  await act(async () =>
    root.render(<AppsView android={readRelease(GITHUB)} />),
  );
  const download = host.querySelector("a[download]") as HTMLAnchorElement;
  expect(download.textContent).toContain("Download for Android");
  expect(download.getAttribute("href")).toBe(ANDROID_APK_URL);
  expect(host.querySelector("svg title")?.textContent).toBe(
    "Scan with your Android phone's camera",
  );
  expect(host.textContent).toContain(
    "Version 0.3.35 · 4.1 MB · updated 18 Oct 2026",
  );
  expect(host.querySelector("code")?.textContent).toBe(SHA);
  const steps = [
    ...host.querySelectorAll('ol[aria-label="Install on Android"] li strong'),
  ];
  expect(steps.map((step) => step.textContent)).toEqual([
    "1. Download and open",
    "2. Allow the install",
    "3. Sign in",
  ]);
  expect(
    host.querySelector('[aria-label^="Android asks to allow installs"]'),
  ).not.toBeNull();
});

it("shows Windows, Mac and Chrome as coming soon, with SmartScreen help ready", async () => {
  await act(async () => root.render(<AppsView android={UNKNOWN_RELEASE} />));
  for (const key of ["windows", "mac", "chrome"]) {
    expect(
      host.querySelector(`[data-platform="${key}"]`)?.textContent,
    ).toContain("Coming soon");
  }
  expect(
    host.querySelector('[aria-label^="Windows protected your PC"]'),
  ).not.toBeNull();
  // Without release details the button still downloads the newest APK.
  expect(host.textContent).toContain("Newest build");
  expect((host.querySelector("a[download]") as HTMLAnchorElement).href).toBe(
    ANDROID_APK_URL,
  );
  expect(host.querySelector("code")).toBeNull();
});

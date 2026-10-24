// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";

import {
  FONT_SCALE_ATTRIBUTE,
  IN_APP_ATTRIBUTE,
  inAppInitScript,
  isAppUserAgent,
} from "./in-app";
import { phoneCallsOpener } from "./in-app-client";

type AppWindow = Window & {
  SXPhone?: unknown;
  SXFontScale?: unknown;
  __sxPhone?: { openCalls?: () => void };
};

afterEach(() => {
  document.documentElement.removeAttribute(IN_APP_ATTRIBUTE);
  document.documentElement.removeAttribute(FONT_SCALE_ATTRIBUTE);
  document.head.querySelector('meta[name="viewport"]')?.remove();
  delete (window as AppWindow).SXPhone;
  delete (window as AppWindow).SXFontScale;
  delete (window as AppWindow).__sxPhone;
  vi.restoreAllMocks();
});

function boot(userAgent: string) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(userAgent);
  new Function(inAppInitScript())();
}

it("reads the app's user-agent token and nothing else", () => {
  expect(
    isAppUserAgent(
      "Mozilla/5.0 (Linux; Android 13) Chrome/141.0 Mobile Safari/537.36 SalesXrayApp/0.2.15",
    ),
  ).toBe(true);
  expect(isAppUserAgent("Mozilla/5.0 (Linux; Android 13) Chrome/141.0")).toBe(
    false,
  );
  expect(isAppUserAgent("NotSalesXrayApp/1")).toBe(false);
  expect(isAppUserAgent("SalesXrayApp/")).toBe(false);
  expect(isAppUserAgent(null)).toBe(false);
});

it("marks the document before paint inside the app", () => {
  boot("Mozilla/5.0 (Linux; Android 13) SalesXrayApp/0.3.1");
  expect(document.documentElement.hasAttribute(IN_APP_ATTRIBUTE)).toBe(true);
});

it("leaves the website alone", () => {
  boot("Mozilla/5.0 (Linux; Android 13) Chrome/141.0 Mobile Safari/537.36");
  expect(document.documentElement.hasAttribute(IN_APP_ATTRIBUTE)).toBe(false);
});

it("recognises app builds from before the token by their phone bridge", () => {
  (window as AppWindow).SXPhone = {};
  boot("Mozilla/5.0 (Linux; Android 13) Chrome/141.0 Mobile Safari/537.36");
  expect(document.documentElement.hasAttribute(IN_APP_ATTRIBUTE)).toBe(true);
});

it("offers the phone's calls only when the app provides them", () => {
  expect(phoneCallsOpener()).toBeNull();
  (window as AppWindow).__sxPhone = {};
  expect(phoneCallsOpener()).toBeNull();
  const openCalls = vi.fn();
  (window as AppWindow).__sxPhone = { openCalls };
  phoneCallsOpener()?.();
  expect(openCalls).toHaveBeenCalledOnce();
});

const DESIGNED =
  "width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content";

function viewport(): HTMLMetaElement {
  const meta = document.createElement("meta");
  meta.name = "viewport";
  meta.content = DESIGNED;
  document.head.append(meta);
  return meta;
}

// Owner's OnePlus, 24 Oct 2026: the phone's font size scales the whole page.
it("draws the page at the phone's font scale, up to 1.2, through the viewport", async () => {
  const meta = viewport();
  (window as AppWindow).SXFontScale = 1.3;
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.27");
  expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe(
    "1.2",
  );
  expect(meta.content).toBe(
    "viewport-fit=cover, interactive-widget=resizes-content, initial-scale=1.2, minimum-scale=1.2, maximum-scale=1.2",
  );
  // Next.js writes the tag again: the scale comes back.
  meta.content = DESIGNED;
  await new Promise((done) => setTimeout(done, 0));
  expect(meta.content).toContain("initial-scale=1.2");
});

it("keeps the designed size at a small font, and without the app's scale", () => {
  const meta = viewport();
  (window as AppWindow).SXFontScale = 0.85;
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.27");
  expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("1");
  expect(meta.content).toBe(DESIGNED);
  delete (window as AppWindow).SXFontScale;
  document.documentElement.removeAttribute(FONT_SCALE_ATTRIBUTE);
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.25");
  expect(document.documentElement.hasAttribute(FONT_SCALE_ATTRIBUTE)).toBe(
    false,
  );
  expect(meta.content).toBe(DESIGNED);
});

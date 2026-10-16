// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";

import { IN_APP_ATTRIBUTE, inAppInitScript, isAppUserAgent } from "./in-app";
import { phoneCallsOpener } from "./in-app-client";

type AppWindow = Window & {
  SXPhone?: unknown;
  __sxPhone?: { openCalls?: () => void };
};

afterEach(() => {
  document.documentElement.removeAttribute(IN_APP_ATTRIBUTE);
  delete (window as AppWindow).SXPhone;
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

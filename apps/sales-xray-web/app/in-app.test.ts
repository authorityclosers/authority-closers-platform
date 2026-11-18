// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";

import {
  FONT_SCALE_ATTRIBUTE,
  followFontScale,
  IN_APP_ATTRIBUTE,
  inAppInitScript,
  isAppUserAgent,
  isIPhoneApp,
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
  document.documentElement.style.fontSize = "";
  localStorage.removeItem("sx.font-scale");
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

// Native-feel spec, 3 Nov 2026: the phone's font size scales text, as sp does,
// through the root size that every type token is in rem of; the layout stays.
it("sets the root font size from the phone's font scale, up to 2", () => {
  (window as AppWindow).SXFontScale = 1.3;
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.27");
  const root = document.documentElement;
  expect(root.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("1.3");
  expect(root.style.fontSize).toBe("130%");
  (window as AppWindow).SXFontScale = 2.4;
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.27");
  expect(root.style.fontSize).toBe("200%");
});

it("keeps the designed size at a small font, and without a scale", () => {
  (window as AppWindow).SXFontScale = 0.85;
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.27");
  const root = document.documentElement;
  expect(root.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("1");
  expect(root.style.fontSize).toBe("100%");
  delete (window as AppWindow).SXFontScale;
  root.removeAttribute(FONT_SCALE_ATTRIBUTE);
  root.style.fontSize = "";
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.25");
  expect(root.hasAttribute(FONT_SCALE_ATTRIBUTE)).toBe(false);
  expect(root.style.fontSize).toBe("");
});

it("follows the scale the app's status reports, from the first paint of the next start", () => {
  followFontScale(1.5);
  const root = document.documentElement;
  expect(root.style.fontSize).toBe("150%");
  root.removeAttribute(FONT_SCALE_ATTRIBUTE);
  root.style.fontSize = "";
  boot("Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.27");
  expect(root.style.fontSize).toBe("150%");
  followFontScale("large");
  expect(root.style.fontSize).toBe("150%");
});

const IPHONE_APP_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 27_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 SalesXrayApp/0.3";
const ANDROID_APP_UA =
  "Mozilla/5.0 (Linux; Android 14; 23124RN87I Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.0.0 Mobile Safari/537.36 SalesXrayApp/0.3";
const IPHONE_SAFARI_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 27_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.2 Mobile/15E148 Safari/604.1";

it("knows the iPhone app by its user agent or Capacitor's platform, never Android or the website", () => {
  expect(isIPhoneApp(IPHONE_APP_UA)).toBe(true);
  expect(isIPhoneApp(ANDROID_APP_UA)).toBe(false);
  expect(isIPhoneApp(IPHONE_SAFARI_UA)).toBe(false);
  expect(
    isIPhoneApp("Mozilla/5.0 (Windows NT 10.0) Chrome/141.0 Safari/537.36"),
  ).toBe(false);
  expect(isIPhoneApp(null)).toBe(false);
  const ios = { Capacitor: { getPlatform: () => "ios" } };
  const android = { Capacitor: { getPlatform: () => "android" } };
  // An iPad's app may say "Macintosh": Capacitor's platform still tells.
  expect(isIPhoneApp("Mozilla/5.0 (Macintosh) SalesXrayApp/0.3", ios)).toBe(
    true,
  );
  expect(isIPhoneApp(IPHONE_APP_UA, android)).toBe(false);
  expect(isIPhoneApp(ANDROID_APP_UA, {})).toBe(false);
  const broken = {
    Capacitor: {
      getPlatform: () => {
        throw new Error("no bridge");
      },
    },
  };
  expect(isIPhoneApp(IPHONE_APP_UA, broken)).toBe(true);
});

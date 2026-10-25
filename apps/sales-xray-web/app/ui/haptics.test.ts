// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { HAPTIC_PATTERNS, haptic, setHaptics, tick } from "./haptics";

type Win = Window & { SXHaptics?: unknown };

const coarse = (yes: boolean) =>
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: yes }) as MediaQueryList),
  );

let vibrate: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vibrate = vi.fn(() => true);
  Object.defineProperty(navigator, "vibrate", {
    value: vibrate,
    configurable: true,
  });
  coarse(true);
});

afterEach(() => {
  delete (window as Win).SXHaptics;
  setHaptics(true);
  vi.unstubAllGlobals();
});

// Android, 25 Oct 2026: window.SXHaptics, one method per token.
it("plays the phone app's own haptic for each token", () => {
  const app = {
    tap: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    urgent: vi.fn(),
  };
  (window as Win).SXHaptics = app;
  haptic("urgent");
  tick();
  expect(app.urgent).toHaveBeenCalledOnce();
  expect(app.tap).toHaveBeenCalledOnce();
  expect(vibrate).not.toHaveBeenCalled();
});

it("asks play(kind) when the app has no method for a token", () => {
  const play = vi.fn();
  (window as Win).SXHaptics = { play };
  haptic("warning");
  expect(play).toHaveBeenCalledWith("warning");
});

it("vibrates a pattern per token in a phone browser", () => {
  haptic("error");
  expect(vibrate).toHaveBeenCalledWith(HAPTIC_PATTERNS.error);
  haptic("tap");
  expect(vibrate).toHaveBeenLastCalledWith(8);
});

it("does nothing with Vibration off, or without a touch screen", () => {
  const app = { urgent: vi.fn() };
  (window as Win).SXHaptics = app;
  setHaptics(false);
  haptic("urgent");
  expect(app.urgent).not.toHaveBeenCalled();
  setHaptics(true);
  delete (window as Win).SXHaptics;
  coarse(false);
  haptic("success");
  expect(vibrate).not.toHaveBeenCalled();
});

it("stays silent in a browser before the first tap on the page", () => {
  Object.defineProperty(navigator, "userActivation", {
    value: { hasBeenActive: false },
    configurable: true,
  });
  haptic("urgent");
  expect(vibrate).not.toHaveBeenCalled();
  Object.defineProperty(navigator, "userActivation", {
    value: { hasBeenActive: true },
    configurable: true,
  });
  haptic("urgent");
  expect(vibrate).toHaveBeenCalledWith(HAPTIC_PATTERNS.urgent);
});

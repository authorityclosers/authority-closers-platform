/**
 * Shake the phone to report a problem, in the Sales X-Ray phone app only (a
 * phone browser would ask for motion permission, and laptops do not shake).
 * A deliberate double shake (four separate hard swings within 1.5 seconds)
 * opens the reporter; picking the phone up, walking, typing or a bump in the
 * pocket does not (26 Oct 2026: a pick-up opened it, because one jolt's
 * readings each counted). It works over an open menu or sheet (owner, 25 Oct
 * 2026: "any menu if on I need the report a bug to work"), never over the reporter
 * itself, never twice within five seconds, and the person can turn it off there.
 */

import { useEffect, useSyncExternalStore } from "react";

const KEY = "sx-shake-to-report";
const CHANGE = "sales-xray:shake-setting";
const THRESHOLD = 20; // m/s² above gravity: a hard flick of the wrist, not a lift
const PEAKS = 4; // two shakes, back and forth each
const WINDOW_MS = 1500;
const SWING_MS = 120; // strong readings closer than this are one swing
const COOLDOWN_MS = 5000;

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function setShakeToReport(on: boolean): void {
  try {
    if (on) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, "off");
  } catch {
    // Private mode: the switch lasts for this page only.
  }
  window.dispatchEvent(new Event(CHANGE));
}

function subscribe(listener: () => void) {
  window.addEventListener(CHANGE, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE, listener);
    window.removeEventListener("storage", listener);
  };
}

export function useShakeSetting(): boolean {
  return useSyncExternalStore(subscribe, read, () => true);
}

/** Counts separate strong swings; true when this reading completes a double shake. */
export function shakeDetector(now: () => number = Date.now) {
  let peaks: number[] = [];
  let last = -Infinity;
  let strong = -Infinity;
  return (x: number, y: number, z: number): boolean => {
    const force = Math.abs(Math.sqrt(x * x + y * y + z * z) - 9.81);
    const at = now();
    if (force < THRESHOLD || at - last < COOLDOWN_MS) return false;
    // One swing gives several strong readings in a row: it counts once.
    const sameSwing = at - strong < SWING_MS;
    strong = at;
    if (sameSwing) return false;
    peaks = [...peaks.filter((peak) => at - peak < WINDOW_MS), at];
    if (peaks.length < PEAKS) return false;
    peaks = [];
    last = at;
    return true;
  };
}

export function useShakeToReport(active: boolean, onShake: () => void): void {
  const on = useShakeSetting();
  useEffect(() => {
    if (!active || !on || typeof window === "undefined") return;
    const shaken = shakeDetector();
    const listen = (event: DeviceMotionEvent) => {
      const a = event.accelerationIncludingGravity;
      if (!a || a.x === null || a.y === null || a.z === null) return;
      if (document.hidden) return;
      if (shaken(a.x, a.y, a.z)) onShake();
    };
    window.addEventListener("devicemotion", listen);
    return () => window.removeEventListener("devicemotion", listen);
  }, [active, on, onShake]);
}

/**
 * Shake the phone to report a problem, in the Sales X-Ray phone app only (a
 * phone browser would ask for motion permission, and laptops do not shake).
 * Three hard shakes within a second open the reporter; walking, typing or a
 * bump in the pocket does not. It works over an open menu or sheet (owner, 25 Oct
 * 2026: "any menu if on I need the report a bug to work"), never over the reporter
 * itself, never twice within five seconds, and the person can turn it off there.
 */

import { useEffect, useSyncExternalStore } from "react";

const KEY = "sx-shake-to-report";
const CHANGE = "sales-xray:shake-setting";
const THRESHOLD = 15; // m/s² above gravity, about a deliberate flick of the wrist
const PEAKS = 3;
const WINDOW_MS = 1000;
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

/** Counts strong peaks; true when this reading completes a shake. */
export function shakeDetector(now: () => number = Date.now) {
  let peaks: number[] = [];
  let last = -Infinity;
  return (x: number, y: number, z: number): boolean => {
    const force = Math.abs(Math.sqrt(x * x + y * y + z * z) - 9.81);
    const at = now();
    if (force < THRESHOLD || at - last < COOLDOWN_MS) return false;
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

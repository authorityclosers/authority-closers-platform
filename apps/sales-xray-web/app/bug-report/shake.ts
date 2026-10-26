/**
 * Shake the phone to report a problem, in the Sales X-Ray phone app only (a
 * phone browser would ask for motion permission, and laptops do not shake).
 * A deliberate shake (three swings within 1.2 seconds, each the other way from
 * the one before) opens the reporter; picking the phone up (one or two jolts),
 * walking, typing or a bump in the pocket does not (26 Oct 2026: v0.93 asked for
 * four swings at 20 m/s², which a normal shake never reached). It works over an open menu or sheet (owner, 25 Oct
 * 2026: "any menu if on I need the report a bug to work"), never over the reporter
 * itself, never twice within five seconds, and the person can turn it off there.
 */

import { useEffect, useSyncExternalStore } from "react";

import { track } from "../telemetry";

const KEY = "sx-shake-to-report";
const CHANGE = "sales-xray:shake-setting";
const THRESHOLD = 13; // m/s² of motion, gravity taken out: a deliberate flick, not a lift
const PEAKS = 3; // swings, each the other way from the one before
const WINDOW_MS = 1200;
const SWING_MS = 80; // a turn sooner than this is the same swing ringing, not a new one
const COOLDOWN_MS = 5000;
const GRAVITY_FOLLOW = 0.9; // how slowly the gravity estimate follows the phone
const NEAR_EVERY_MS = 30_000; // at most one near miss in telemetry per half minute

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

type Swing = { at: number; axis: number; sign: number; force: number };

/** The strongest swing's force, whole m/s². */
function strongest(swings: readonly Swing[]): number {
  return Math.round(Math.max(...swings.map((swing) => swing.force)));
}

/**
 * True when a reading completes a shake. `peak()` and `swings()` tell the last
 * shake's strongest swing (m/s²) and its swings; `near` hears of a window that
 * reached two swings but not three, to tune from real phones.
 */
export function shakeDetector(
  now: () => number = Date.now,
  near?: (peak: number, swings: number) => void,
) {
  let gravity: number[] | null = null;
  let swings: Swing[] = [];
  let opened = -Infinity;
  let lastPeak = 0;
  let lastSwings = 0;
  const check = (x: number, y: number, z: number): boolean => {
    const at = now();
    const reading = [x, y, z];
    // Motion is the reading less gravity, which a slow average follows, so a
    // sideways shake counts as much as an up-and-down one.
    const base = gravity ?? reading;
    const motion = reading.map((value, i) => value - base[i]);
    gravity = base.map(
      (g, i) => GRAVITY_FOLLOW * g + (1 - GRAVITY_FOLLOW) * reading[i],
    );
    if (swings.length && at - swings[0].at > WINDOW_MS) {
      if (swings.length >= 2) near?.(strongest(swings), swings.length);
      swings = [];
    }
    const force = Math.hypot(motion[0], motion[1], motion[2]);
    if (force < THRESHOLD || at - opened < COOLDOWN_MS) return false;
    const axis = motion.reduce(
      (best, value, i) => (Math.abs(value) > Math.abs(motion[best]) ? i : best),
      0,
    );
    const sign = Math.sign(motion[axis]);
    const previous = swings.at(-1);
    // The same way as the swing before, or a turn sooner than a swing takes, is
    // still that swing: one lift or jolt never counts twice.
    if (
      previous &&
      ((previous.axis === axis && previous.sign === sign) ||
        at - previous.at < SWING_MS)
    ) {
      previous.force = Math.max(previous.force, force);
      return false;
    }
    swings.push({ at, axis, sign, force });
    if (swings.length < PEAKS) return false;
    lastPeak = strongest(swings);
    lastSwings = swings.length;
    swings = [];
    opened = at;
    return true;
  };
  return Object.assign(check, {
    peak: () => lastPeak,
    swings: () => lastSwings,
  });
}

export function useShakeToReport(active: boolean, onShake: () => void): void {
  const on = useShakeSetting();
  useEffect(() => {
    if (!active || !on || typeof window === "undefined") return;
    let nearSent = -Infinity;
    // How hard real shakes are on real phones, numbers only (26 Oct 2026).
    const shaken = shakeDetector(Date.now, (peak, swings) => {
      const at = Date.now();
      if (at - nearSent < NEAR_EVERY_MS) return;
      nearSent = at;
      track("sx.shake", { outcome: "near", peak, swings });
    });
    const listen = (event: DeviceMotionEvent) => {
      const a = event.accelerationIncludingGravity;
      if (!a || a.x === null || a.y === null || a.z === null) return;
      if (document.hidden) return;
      if (!shaken(a.x, a.y, a.z)) return;
      track("sx.shake", {
        outcome: "opened",
        peak: shaken.peak(),
        swings: shaken.swings(),
      });
      onShake();
    };
    window.addEventListener("devicemotion", listen);
    return () => window.removeEventListener("devicemotion", listen);
  }, [active, on, onShake]);
}

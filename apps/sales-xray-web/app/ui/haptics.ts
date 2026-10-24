/**
 * A light tap felt in the hand (design system v2, owner 20 Oct: "top notch
 * apple like animations"): when a sheet passes the point where letting go
 * closes it, a switch flips, the phone's tab changes or + opens Add. Phones only, and only where the device can:
 * the phone app's haptics plugin when it has one, else a 8 ms vibration.
 * Never a carrier of meaning; nothing breaks without it.
 */
type HapticsWindow = Window & {
  Capacitor?: {
    Plugins?: {
      Haptics?: { impact?: (options: { style: string }) => Promise<void> };
    };
  };
};

const HAPTICS_KEY = "sx-haptics";

/**
 * Vibration (Settings, Phone & alerts, 24 Oct 2026): on unless turned off on
 * this device; both this tick and the phone app's buzz follow it.
 */
export function hapticsOn(): boolean {
  try {
    return window.localStorage.getItem(HAPTICS_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setHaptics(on: boolean): void {
  try {
    if (on) window.localStorage.removeItem(HAPTICS_KEY);
    else window.localStorage.setItem(HAPTICS_KEY, "off");
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
}

export function tick() {
  if (typeof window === "undefined" || !hapticsOn()) return;
  try {
    if (!window.matchMedia?.("(pointer: coarse)").matches) return;
    const haptics = (window as HapticsWindow).Capacitor?.Plugins?.Haptics;
    if (haptics?.impact) {
      void haptics.impact({ style: "LIGHT" }).catch(() => undefined);
      return;
    }
    navigator.vibrate?.(8);
  } catch {
    // A refused vibration changes nothing.
  }
}

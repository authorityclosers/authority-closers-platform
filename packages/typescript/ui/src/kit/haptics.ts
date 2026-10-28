/**
 * Haptics for the whole app (owner program, 25 Oct 2026, item 3): one set of
 * tokens, used everywhere: tap, success, warning, error and urgent. Phones
 * only, and only where the device can: the phone app's own haptics
 * (window.SXHaptics, Android 25 Oct), else its older haptics plugin, else a
 * vibration pattern in a phone browser. Never a carrier of meaning; nothing
 * breaks without it.
 */
export type HapticKind = "tap" | "success" | "warning" | "error" | "urgent";

export const HAPTIC_KINDS: readonly HapticKind[] = [
  "tap",
  "success",
  "warning",
  "error",
  "urgent",
];

type NativeHaptics = Partial<Record<HapticKind, () => void>> & {
  play?: (kind: string) => void;
};

type HapticsWindow = Window & {
  /** The phone app's haptics, set before the page's scripts (app only). */
  SXHaptics?: NativeHaptics;
  Capacitor?: {
    Plugins?: {
      Haptics?: {
        impact?: (options: { style: string }) => Promise<void>;
        notification?: (options: { type: string }) => Promise<void>;
      };
    };
  };
};

/**
 * A phone browser's patterns (ms on, off, on…): tap a tick, success two
 * light beats, warning two firmer, error three, urgent three long pulses.
 */
export const HAPTIC_PATTERNS: Record<HapticKind, number | number[]> = {
  tap: 8,
  success: [12, 60, 18],
  warning: [24, 80, 24],
  error: [36, 60, 36, 60, 36],
  urgent: [90, 70, 90, 70, 90],
};

const PLUGIN_TYPE: Partial<Record<HapticKind, string>> = {
  success: "SUCCESS",
  warning: "WARNING",
  error: "ERROR",
  urgent: "ERROR",
};

const HAPTICS_KEY = "sx-haptics";

/**
 * Vibration (Settings, Phone & alerts, 24 Oct 2026): on unless turned off on
 * this device; every haptic here and the phone app's buzz follow it.
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

/** One haptic by its token, when Vibration is on and the device can. */
export function haptic(kind: HapticKind): void {
  if (typeof window === "undefined" || !hapticsOn()) return;
  try {
    const native = (window as HapticsWindow).SXHaptics;
    if (native) {
      const own = native[kind];
      if (typeof own === "function") own.call(native);
      else native.play?.(kind);
      return;
    }
    if (!window.matchMedia?.("(pointer: coarse)").matches) return;
    const plugin = (window as HapticsWindow).Capacitor?.Plugins?.Haptics;
    const type = PLUGIN_TYPE[kind];
    if (type && plugin?.notification) {
      void plugin.notification({ type }).catch(() => undefined);
      return;
    }
    if (!type && plugin?.impact) {
      void plugin.impact({ style: "LIGHT" }).catch(() => undefined);
      return;
    }
    // Browsers refuse a vibration before the first tap on the page (and log
    // it): an alert that lands before then stays silent.
    const activation = (
      navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }
    ).userActivation;
    if (activation && !activation.hasBeenActive) return;
    navigator.vibrate?.(HAPTIC_PATTERNS[kind]);
  } catch {
    // A refused vibration changes nothing.
  }
}

/**
 * A light tap felt in the hand (design system v2, owner 20 Oct: "top notch
 * apple like animations"): when a sheet passes the point where letting go
 * closes it, a switch flips, the phone's tab changes or + opens Add.
 */
export function tick() {
  haptic("tap");
}

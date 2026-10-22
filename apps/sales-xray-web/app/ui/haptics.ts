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

export function tick() {
  if (typeof window === "undefined") return;
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

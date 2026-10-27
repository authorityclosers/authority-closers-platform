/**
 * What happens to a Call press, told honestly (27 Oct 2026). Until now a "Call
 * press" was any finger that touched Call. A third of those on the company
 * phone never became a call: a tap while the sheet was gliding, or a swipe
 * that started on the button. Call buttons carry `data-sx-call`, which the
 * automatic tap timing skips (telemetry-auto.tsx). They report here instead:
 *
 * - `started`: a call really started, by touch or by click. Its tap-to-response
 *   time (call_start) begins then;
 * - `rescued`: it started on a touch whose click never came, a tap the glide
 *   would have lost before the fix;
 * - `touch_no_call`: a touch on Call that placed no call (a drag, a finger
 *   that moved, a long press);
 * - the phone app's hand-off: `status`, `permits`, `bridge_ok`,
 *   `bridge_error` and `fallback_tel`.
 *
 * Codes and milliseconds only, never the number or the lead.
 */
import { screenOf, timeAction, track } from "../telemetry";
import type { FirstTapOutcome } from "./first-tap";

type Step =
  | "status"
  | "permits"
  | "bridge_ok"
  | "bridge_error"
  | "fallback_tel";

const here = () =>
  typeof window === "undefined"
    ? undefined
    : screenOf(window.location.pathname, window.location.search);

/** One Call press's outcome (first-tap.ts's report). */
export function reportCallPress(outcome: FirstTapOutcome): void {
  try {
    if (outcome === "touch" || outcome === "click") {
      timeAction("call_start");
      track("sx.phone_call", { step: "started", via: outcome, screen: here() });
    } else if (outcome === "rescued") {
      track("sx.phone_call", { step: "rescued", screen: here() });
    } else {
      track("sx.phone_call", {
        step: "touch_no_call",
        why: outcome,
        screen: here(),
      });
    }
  } catch {
    // Telemetry never stops a call.
  }
}

/** One step of the phone app's hand-off, with how long it took. */
export function callStep(
  step: Step,
  extra: {
    ms?: number;
    mode?: "dialer" | "direct" | "browser";
    why?: "timeout" | "error";
  } = {},
): void {
  try {
    track("sx.phone_call", {
      step,
      ...(typeof extra.ms === "number"
        ? { ms: Math.max(0, Math.min(60_000, Math.round(extra.ms))) }
        : {}),
      ...(extra.mode ? { mode: extra.mode } : {}),
      ...(extra.why ? { why: extra.why } : {}),
      screen: here(),
    });
  } catch {
    // Telemetry never stops a call.
  }
}

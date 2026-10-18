/**
 * Words for a call the seller's phone logged by itself (UX study item 5): one
 * made from the phone dialer or taken on the phone, not from the lead's Call
 * button. The lead's History shows them.
 */

import type { LeadEvent } from "./leads-client";

/** 3:12, the way a phone's call log shows talk time. */
export function clockTime(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** A call the seller's phone logged by itself, made outside the lead's Call button. */
export function phoneCallText(
  event: LeadEvent,
  who: string,
): { title: string; detail?: string } {
  const talk = event.duration_seconds ? clockTime(event.duration_seconds) : "";
  switch (event.direction) {
    case "incoming":
      return {
        title: `They called ${who}${talk ? ` · ${talk}` : ""}`,
        detail: "From the phone's call log",
      };
    case "missed":
      return {
        title: "Missed call from them",
        detail: `On ${who}'s phone. Call them back.`,
      };
    case "rejected":
      return {
        title: `${who} cut their call`,
        detail: "From the phone's call log",
      };
    case "blocked":
      return {
        title: "Their call was blocked",
        detail: `On ${who}'s phone`,
      };
    default:
      return {
        title: `${who} called · ${talk || "not connected"}`,
        detail: "From the phone dialer",
      };
  }
}

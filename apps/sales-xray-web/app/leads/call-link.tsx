"use client";

/**
 * A `tel:` link that calls on the first touch (first-tap.ts), even while the
 * sheet still glides (27 Oct 2026). `onCall` decides how the call goes (the
 * company number, the phone app, or the browser following the link). Press
 * outcomes are counted in phone-call-steps.ts, and auto-timing skips the link
 * (`data-sx-call`).
 */
import type { AnchorHTMLAttributes, ReactNode } from "react";

import { firstTap, type FirstTapEvent } from "./first-tap";
import { dialPhone } from "./leads-client";
import { reportCallPress } from "./phone-call-steps";

/** No double dial (Leads part 04): a second tap on the same number within
 *  LOCK_MS is the same call, until the page hides (the dialer opened). */
const LOCK_MS = 2500;
let lastCall: { phone: string; at: number } | null = null;
if (typeof document !== "undefined")
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) lastCall = null;
  });

/** True when a press starts a call; false for a second tap on the same number
 *  within LOCK_MS. */
function startsCall(phone: string): boolean {
  const now = Date.now();
  if (lastCall?.phone === phone && now - lastCall.at < LOCK_MS) return false;
  lastCall = { phone, at: now };
  return true;
}

export function CallLink({
  phone,
  onCall,
  children,
  ...rest
}: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "onClick"> & {
  phone: string;
  onCall: (event: FirstTapEvent<HTMLAnchorElement>) => void;
  children: ReactNode;
}) {
  const callOnce = (event: FirstTapEvent<HTMLAnchorElement>) => {
    if (!startsCall(phone)) {
      event.preventDefault();
      return;
    }
    onCall(event);
  };
  return (
    <a
      {...rest}
      href={`tel:${dialPhone(phone)}`}
      data-sx-call=""
      {...firstTap(callOnce, reportCallPress)}
    >
      {children}
    </a>
  );
}

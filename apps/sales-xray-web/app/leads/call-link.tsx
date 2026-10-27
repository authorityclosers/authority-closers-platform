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
import { reportCallPress } from "./phone-call-steps";

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
  return (
    <a
      {...rest}
      href={`tel:${phone}`}
      data-sx-call=""
      {...firstTap(onCall, reportCallPress)}
    >
      {children}
    </a>
  );
}

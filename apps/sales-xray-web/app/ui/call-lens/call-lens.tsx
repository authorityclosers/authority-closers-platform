"use client";

/**
 * The Call (L0 expression brief; Dipak's design, 4 Nov 2026). Every primary
 * Call looks the same: a full-width teal pill, its phone glyph beside the
 * outcome in words ("Call now", "Start Cold Calling"). The fill meets 7:1
 * against its label, for a phone in the sun (FRAMEWORK L4). A press answers
 * in 100 ms with a 10 % state layer and a tap haptic; nothing else moves. The
 * layer is drawn by the pill itself, so it adds no element to the page (the
 * 2 Nov rule).
 */

import { PhoneCall } from "lucide-react";
import Link from "next/link";
import type { MouseEvent, ReactNode } from "react";

import { haptic } from "../haptics";
import styles from "./call-lens.module.css";

export function CallLens({
  href,
  children,
  onClick,
}: {
  href: string;
  /** The outcome in words: "Call Rohan now". */
  children: ReactNode;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  return (
    <Link
      className={styles.capsule}
      href={href}
      data-call-lens=""
      onClick={(event) => {
        haptic("tap");
        onClick?.(event);
      }}
    >
      <PhoneCall
        className={styles.glyph}
        size={20}
        strokeWidth={2}
        aria-hidden="true"
      />
      {children}
    </Link>
  );
}

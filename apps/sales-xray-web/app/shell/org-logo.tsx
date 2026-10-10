"use client";

import { useState, type ReactNode } from "react";

import styles from "./org-logo.module.css";

/**
 * A workspace's square logo filling its tile. Without a logo, or if it fails
 * to load, the tile keeps what it showed before (initials or an icon).
 */
export function OrgLogo({
  src,
  fallback,
}: {
  src: string | null | undefined;
  fallback: ReactNode;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) return fallback;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- The private logo must use the signed-in browser session directly.
    <img
      className={styles.logo}
      src={src}
      alt=""
      referrerPolicy="no-referrer"
      decoding="async"
      data-org-logo=""
      onError={() => setFailed(src)}
    />
  );
}

"use client";

/**
 * The organisation's settings live in its hub (owner, 23 Oct 2026: "if
 * organisation is clicked there should be clearly visible all management
 * options"). An old /settings address (a saved link, a connect flow coming
 * back with ?connected=...) goes to its tab there, its own query kept.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** The hub address with the old address's own query and hash kept. */
export function hubTarget(to: string, search: string, hash = ""): string {
  const target = new URL(to, "https://x.invalid");
  new URLSearchParams(search).forEach((value, key) => {
    if (key !== "tab" && key !== "part") target.searchParams.set(key, value);
  });
  return `${target.pathname}${target.search}${hash}`;
}

export function HubRedirect({ to }: { to: string }) {
  const router = useRouter();
  useEffect(() => {
    router.replace(hubTarget(to, window.location.search, window.location.hash));
  }, [router, to]);
  return (
    <p role="status" aria-busy="true">
      Opening the organisation…
    </p>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** While a stage runs, re-read the server page every few seconds; stop when nothing runs. */
export function LiveRefresh({
  active,
  ms = 5000,
}: {
  active: boolean;
  ms?: number;
}) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => router.refresh(), ms);
    return () => window.clearInterval(timer);
  }, [active, ms, router]);
  return null;
}

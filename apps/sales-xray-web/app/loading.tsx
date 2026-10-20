"use client";

import { RouteLoading } from "./shell/route-loading";

/**
 * Shown by Next.js around every top-level page while it loads: the outline
 * of the screen being opened, never New analysis for another page (owner,
 * 20 Oct).
 */
export default function Loading() {
  return <RouteLoading />;
}

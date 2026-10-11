"use client";

import { CallOpeningSkeleton } from "../../../shell/call-opening-skeleton";

/** A saved call opens with its own outline, never New analysis's. */
export default function CallLoading() {
  return <CallOpeningSkeleton />;
}

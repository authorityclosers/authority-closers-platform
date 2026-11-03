"use client";

import { watchTapReach } from "@ac/ui/kit/tap-reach";
import { useEffect } from "react";

/** Every control answers a 44 px tap on a touch screen (kit/tap-reach.ts); mounted once in the root layout. */
export function TapReach() {
  useEffect(() => watchTapReach(), []);
  return null;
}

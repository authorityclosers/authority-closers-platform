"use client";

import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { useContext } from "react";

/**
 * The App Router, or null where the shell is drawn without one (tests,
 * static previews). next/navigation's useRouter throws there; the shell's
 * prefetching and screen moves are extras, so they simply step aside.
 */
export function useAppRouter() {
  return useContext(AppRouterContext);
}

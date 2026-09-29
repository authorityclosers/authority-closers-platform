"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { StandaloneStudio } from "./standalone-studio";

const SHELL_ROUTES = new Set(["/", "/dashboard", "/calls", "/account"]);

/**
 * Checks the session once per full-page load (layout mount).
 * Pages that live inside the Lightbox shell get StandaloneStudio;
 * other pages (login, auth, review fixtures) receive their children directly.
 */
export function AppSession({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (SHELL_ROUTES.has(pathname)) {
    return <StandaloneStudio>{children}</StandaloneStudio>;
  }
  return <>{children}</>;
}

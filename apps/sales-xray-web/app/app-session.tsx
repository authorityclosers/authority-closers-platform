"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { callIdFromPath } from "./analysis-routes";
import { StandaloneStudio } from "./standalone-studio";

const SHELL_ROUTES = new Set([
  "/",
  "/dashboard",
  "/calls",
  "/account",
  "/organisation",
  "/analysis",
  "/analysis/new",
  "/analysis/calls",
]);

function isShellRoute(pathname: string | null) {
  if (!pathname) return false;
  // Static exports use trailing slashes for the same application pages.
  const route = pathname.replace(/\/$/, "") || "/";
  return SHELL_ROUTES.has(route) || callIdFromPath(route) !== null;
}

/**
 * Checks the session once per full-page load (layout mount).
 * Pages that live inside the Lightbox shell get StandaloneStudio;
 * other pages (login, auth, review fixtures) receive their children directly.
 */
export function AppSession({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (isShellRoute(pathname)) {
    return <StandaloneStudio>{children}</StandaloneStudio>;
  }
  return <>{children}</>;
}

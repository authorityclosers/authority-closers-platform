"use client";

import { useEffect } from "react";

/**
 * Inside the Sales X-Ray phone app, tells the app this page is up (live web
 * updates, owner 28 Oct 2026: web releases reach the app with no Play build).
 * The app downloads each production release's web bundle and uses it from
 * the next start; a new bundle that doesn't say it is up within 15 seconds is
 * rolled back (sales-xray-apps LiveWeb.java). Mounted once in the root layout,
 * so the signal comes only after React has started this page. Outside the app,
 * and in app builds without live updates, it does nothing.
 */
type Channel = { postMessage: (data: string) => void };

export function signalWebReady(
  target: unknown = (globalThis as { SXPhone?: unknown }).SXPhone,
): boolean {
  const channel = target as Partial<Channel> | undefined;
  if (!channel || typeof channel.postMessage !== "function") return false;
  try {
    channel.postMessage(
      JSON.stringify({
        id: "web-ready",
        method: "webReady",
        args: { release: process.env.NEXT_PUBLIC_AC_RELEASE_ID ?? "" },
      }),
    );
    return true;
  } catch {
    return false;
  }
}

export function WebReady(): null {
  useEffect(() => {
    signalWebReady();
  }, []);
  return null;
}

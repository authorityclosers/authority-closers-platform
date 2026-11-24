"use client";

/**
 * The offline screen's service worker, registered here (v1.96 device polish,
 * lane P: after the first load, a reload or a tab switch with no internet
 * showed Chrome's dino page). public/sw.js says what it does: pages always
 * from the network, its own offline screen only when that fails, build files
 * kept per release, the API, sign-in, uploads and recordings never touched.
 *
 * Never inside the phone apps: Android answers the app's pages from its own
 * signed web bundle (sales-xray-apps BundledWeb.java), and a worker there
 * could answer before the bundle does; the iPhone app is Capacitor. A worker
 * found there is removed.
 *
 * Kill switch, three ways:
 * - Everyone: AC_SALES_XRAY_SERVICE_WORKER=off in the web container's
 *   environment, then restart it (no rebuild). Each browser removes the worker
 *   and its files on its next page.
 * - One browser: open any page with ?sw=off (or the address /sw-off). It stays
 *   off in that browser until ?sw=on.
 * - A release can also ship a public/sw.js that only unregisters itself.
 */
import { useEffect } from "react";

import { isAppUserAgent } from "../in-app";
import { releaseLabel } from "../telemetry";

export const WORKER_URL = "/sw.js";
export const CACHE_PREFIX = "sx-shell-";
export const OFF_KEY = "sx.sw-off";

type PhoneWindow = { SXPhone?: unknown; Capacitor?: unknown };

/** Inside a phone app (its user-agent token, or its bridge on the page). */
export function inPhoneApp(win: Window): boolean {
  const phone = win as Window & PhoneWindow;
  return (
    isAppUserAgent(win.navigator.userAgent) ||
    typeof phone.SXPhone !== "undefined" ||
    typeof phone.Capacitor !== "undefined"
  );
}

/** ?sw=off / ?sw=on / the address /sw-off: this browser's own switch, kept. */
export function readLocalSwitch(win: Window): boolean {
  let off = false;
  try {
    const asked = new URLSearchParams(win.location.search).get("sw");
    if (
      asked === "off" ||
      win.location.pathname.replace(/\/$/, "") === "/sw-off"
    )
      win.localStorage.setItem(OFF_KEY, "1");
    else if (asked === "on") win.localStorage.removeItem(OFF_KEY);
    off = win.localStorage.getItem(OFF_KEY) === "1";
  } catch {
    // Storage blocked: only the address decides.
    off = new URLSearchParams(win.location.search).get("sw") === "off";
  }
  return off;
}

/** The worker's address for this build: its release names its files. */
export function workerUrl(release: string | null): string {
  return `${WORKER_URL}?v=${encodeURIComponent(release ?? "dev")}`;
}

/** Removes this site's worker and the files it kept. */
export async function removeWorker(win: Window): Promise<void> {
  try {
    const registrations = await win.navigator.serviceWorker.getRegistrations();
    await Promise.all(
      registrations
        .filter((registration) =>
          [registration.active, registration.waiting, registration.installing]
            .map((worker) => worker?.scriptURL ?? "")
            .some(
              (url) => new URL(url, win.location.href).pathname === WORKER_URL,
            ),
        )
        .map((registration) => registration.unregister()),
    );
  } catch {
    // Nothing registered, or the browser refuses: nothing to remove.
  }
  try {
    const names = await win.caches.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith(CACHE_PREFIX))
        .map((name) => win.caches.delete(name)),
    );
  } catch {
    // No Cache Storage here.
  }
}

/** The build files this page already loaded, for the worker to keep too. */
function loadedBuildFiles(win: Window): string[] {
  try {
    return win.performance
      .getEntriesByType("resource")
      .map((entry) => entry.name)
      .filter((name) => {
        try {
          const url = new URL(name);
          return (
            url.origin === win.location.origin &&
            url.pathname.startsWith("/_next/static/")
          );
        } catch {
          return false;
        }
      });
  } catch {
    return [];
  }
}

export async function startWorker(win: Window, off: boolean): Promise<void> {
  if (!("serviceWorker" in win.navigator) || !win.isSecureContext) return;
  if (off || readLocalSwitch(win) || inPhoneApp(win)) {
    await removeWorker(win);
    return;
  }
  const release = releaseLabel(process.env.NEXT_PUBLIC_AC_RELEASE_ID);
  try {
    const registration = await win.navigator.serviceWorker.register(
      workerUrl(release),
      { scope: "/", updateViaCache: "none" },
    );
    const worker =
      registration.active ?? registration.waiting ?? registration.installing;
    worker?.postMessage({ type: "warm", urls: loadedBuildFiles(win) });
  } catch {
    // Private browsing, blocked storage or policy: the app works as before.
  }
}

/** Runs once per page load, after the page has loaded, so it never slows it. */
export function ShellWorker({ off }: { off: boolean }) {
  useEffect(() => {
    let cancelled = false;
    const go = () => {
      if (cancelled) return;
      void startWorker(window, off).then(() => {
        if (
          !cancelled &&
          window.location.pathname.replace(/\/$/, "") === "/sw-off"
        )
          window.location.replace("/dashboard");
      });
    };
    if (document.readyState === "complete") {
      const timer = window.setTimeout(go, 1500);
      return () => {
        cancelled = true;
        window.clearTimeout(timer);
      };
    }
    const onLoad = () => window.setTimeout(go, 1500);
    window.addEventListener("load", onLoad, { once: true });
    return () => {
      cancelled = true;
      window.removeEventListener("load", onLoad);
    };
  }, [off]);
  return null;
}

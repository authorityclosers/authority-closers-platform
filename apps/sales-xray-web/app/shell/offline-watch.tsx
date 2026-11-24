"use client";

/**
 * No internet, said once, calmly (v1.96 device polish, lane P: offline scored
 * 2 of 10). While the phone has no connection one line says "No internet.
 * Showing what was loaded." with Try again; the screen keeps what it shows.
 * A tap on another screen's link stays here while offline (it would only
 * reach the offline screen) and brings the line back if it was closed. Once
 * the connection is back the line goes and the screen reads afresh: the
 * screens' own "online" listeners and a router refresh.
 */
import { useEffect } from "react";

import { dismissNotice, notify } from "../notice-center";
import { useAppRouter } from "./app-router";

export const OFFLINE_NOTICE = "offline";

/** A quick look at whether the site answers (any answer counts: the network is there). */
export async function reachable(
  fetcher: typeof fetch = fetch,
): Promise<boolean> {
  try {
    await fetcher(`/favicon.ico?online=${Date.now()}`, {
      cache: "no-store",
      credentials: "same-origin",
    });
    return true;
  } catch {
    return false;
  }
}

/** A tap on a link to another screen of this site, opened in this tab. */
export function inAppLinkTap(event: MouseEvent, origin: string): boolean {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  )
    return false;
  const target = event.target instanceof Element ? event.target : null;
  const link = target?.closest("a[href]");
  if (!(link instanceof HTMLAnchorElement)) return false;
  if (link.target && link.target !== "_self") return false;
  if (link.hasAttribute("download")) return false;
  try {
    const url = new URL(link.href);
    if (url.origin !== origin) return false;
    const here = new URL(window.location.href);
    // The same screen with another #part: no page to fetch.
    return !(url.pathname === here.pathname && url.search === here.search);
  } catch {
    return false;
  }
}

export function OfflineWatch() {
  // Null where the shell is drawn without the App Router (tests, previews).
  const router = useAppRouter();
  useEffect(() => {
    let shown = false;
    const show = (stillOff = false) => {
      shown = true;
      notify({
        id: OFFLINE_NOTICE,
        tone: "info",
        title: "No internet",
        message: stillOff
          ? "Still no internet. Showing what was loaded."
          : "Showing what was loaded.",
        action: { label: "Try again", run: tryAgain },
        timeout: 0,
        dock: true,
        noReport: true,
      });
    };
    const back = () => {
      if (!shown) return;
      shown = false;
      dismissNotice(OFFLINE_NOTICE);
      router?.refresh();
    };
    const tryAgain = () => {
      void reachable().then((ok) => {
        if (ok && navigator.onLine !== false) back();
        else show(true);
      });
    };
    const onOffline = () => show();
    const onOnline = () => back();
    // A press on a link to another screen, while offline: the app's links
    // start the next screen's outline on the press itself (screen-link.tsx),
    // so the press and the click both stop here, before the app hears them.
    const onPress = (event: MouseEvent) => {
      if (navigator.onLine !== false) return;
      if (!inAppLinkTap(event, window.location.origin)) return;
      event.stopPropagation();
      if (event.type === "click") {
        event.preventDefault();
        show(true);
      }
    };
    if (navigator.onLine === false) show();
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    // On the window, capturing: ahead of React's own listeners on the document.
    window.addEventListener("pointerdown", onPress, true);
    window.addEventListener("click", onPress, true);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("pointerdown", onPress, true);
      window.removeEventListener("click", onPress, true);
    };
  }, [router]);
  return null;
}

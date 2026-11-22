"use client";

/**
 * "Slow network. Still loading…" (v1.96 device polish, lane P: on slow 3G
 * Calls was a blank grey screen at 3 s and Leads a skeleton for 22 s, with
 * nothing said). One small pill, the same on every screen, once a screen has
 * been loading for 5 seconds; it goes as soon as the screen is up.
 *
 * Before the app's scripts arrive (a cold start on a slow line) a tiny script
 * in the page shows it (slowNetworkScript); after that this component decides,
 * from the loading outlines on screen (aria-busy, as the stuck check reads
 * them). At 15 seconds the stuck check's card (stuck-watch.tsx) takes over,
 * with Reload, and the pill steps aside. Offline has its own line instead.
 */
import { useEffect } from "react";

import { useNoticeShown } from "../notice-center";
import { loadingOnScreen, STUCK_NOTICE } from "./stuck-watch";
import styles from "./slow-network.module.css";
import {
  LIVE_ATTRIBUTE,
  SLOW_AFTER_MS,
  SLOW_ATTRIBUTE,
} from "./slow-network-script";

export { SLOW_AFTER_MS, SLOW_ATTRIBUTE } from "./slow-network-script";

/** Whether the pill shows: loading for 5 s or more, online, with no stuck card up. */
export function slowNow(
  busySince: number | null,
  now: number,
  online: boolean,
  stuckCard: boolean,
): boolean {
  return (
    busySince !== null &&
    now - busySince >= SLOW_AFTER_MS &&
    online &&
    !stuckCard
  );
}

const CHECK_EVERY_MS = 1_000;

export function SlowNetwork() {
  const stuckCard = useNoticeShown(STUCK_NOTICE);
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute(LIVE_ATTRIBUTE, "");
    // The first screen counts from the page's start, so a cold start's wait counts too.
    let since: number | null = loadingOnScreen()
      ? Date.now() - Math.round(performance.now())
      : null;
    const check = () => {
      if (!loadingOnScreen()) since = null;
      else since ??= Date.now();
      if (slowNow(since, Date.now(), navigator.onLine !== false, stuckCard))
        root.setAttribute(SLOW_ATTRIBUTE, "");
      else root.removeAttribute(SLOW_ATTRIBUTE);
    };
    check();
    const timer = window.setInterval(check, CHECK_EVERY_MS);
    return () => {
      window.clearInterval(timer);
      root.removeAttribute(SLOW_ATTRIBUTE);
    };
  }, [stuckCard]);
  return (
    <div className={styles.pill} data-sx-slow-pill="" role="status">
      <span className={styles.dot} aria-hidden="true" />
      Slow network. Still loading…
    </div>
  );
}

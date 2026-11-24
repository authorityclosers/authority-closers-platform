"use client";

/**
 * "Get the Android app" (owner, 13 Nov 2026): a tester who is signed in on an
 * Android phone's browser, not in the app, and whose Google account the team
 * has added to the Play group, gets one big sheet with Play's two steps.
 * It asks the server once per page load, only on the signed-in app's own
 * pages, and not again in this tab once the answer is "not ready".
 *
 * Polite (v1.96 device polish, lane P: it opened about a second after landing
 * on every visit and blocked the page): at most once every 7 days, counted from
 * when it last showed or was closed; only after the page has settled and the
 * person has paused, never over a task (a lead open, the call wrap-up, any
 * other sheet or dialog, a loading screen); never in the phone app's WebView.
 */
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { isShellRoute } from "../app-session";
import { Sheet } from "../ui/sheet";
import { COPY } from "./testers-copy";
import {
  isAndroidBrowser,
  readTesterMe,
  type TesterRead,
} from "./testers-client";
import { PlaySteps } from "./testers-page";
import styles from "./testers.module.css";

export const SNOOZE_KEY = "sx.testers.app-sheet";
export const SETTLED_KEY = "sx.testers.settled";
export const SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;
/** The page has been up this long, and the person still this long, before it may open. */
export const SETTLE_MS = 6_000;
export const STILL_MS = 3_000;
const CHECK_EVERY_MS = 1_000;

// One read per page load, shared by every render (React may run an effect
// twice in development; the second run waits on the same answer).
let read: Promise<TesterRead> | null = null;

/** For tests: forget this page load's answer. */
export function forgetTesterRead(): void {
  read = null;
}

function snoozed(now: number): boolean {
  try {
    const until = Number(localStorage.getItem(SNOOZE_KEY) ?? "0");
    return Number.isFinite(until) && until > now;
  } catch {
    return false;
  }
}

function snooze(): void {
  try {
    localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS));
  } catch {
    // Without storage it may come back next visit: harmless.
  }
}

function settled(): boolean {
  try {
    return sessionStorage.getItem(SETTLED_KEY) === "1";
  } catch {
    return false;
  }
}

function settle(): void {
  try {
    sessionStorage.setItem(SETTLED_KEY, "1");
  } catch {
    // Without storage, the next page load asks once more: harmless.
  }
}

/** The phone app's own page, even one whose user agent lacks the token: its bridge is there. */
function inPhoneApp(): boolean {
  const win = window as Window & { SXPhone?: unknown; Capacitor?: unknown };
  return (
    typeof win.SXPhone !== "undefined" || typeof win.Capacitor !== "undefined"
  );
}

/**
 * Something is in progress on screen: a lead open (its page or sheet), the
 * call wrap-up, any other sheet or dialog, or a screen still loading.
 */
export function busyWithTask(doc: Document, href: string): boolean {
  try {
    if (new URL(href).searchParams.has("lead")) return true;
  } catch {
    // An address we can't read: judge by the screen alone.
  }
  return Boolean(
    doc.querySelector(
      '[role="dialog"], [aria-modal="true"], dialog[open], [aria-busy="true"], [data-wrap-up]',
    ),
  );
}

export function GetAppSheet() {
  const pathname = usePathname();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (
      !isShellRoute(pathname) ||
      !isAndroidBrowser(navigator.userAgent) ||
      inPhoneApp() ||
      snoozed(Date.now()) ||
      settled()
    )
      return;
    let live = true;
    let timer: number | undefined;
    let lastTouch = Date.now();
    const touched = () => {
      lastTouch = Date.now();
    };
    const events = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    for (const name of events)
      window.addEventListener(name, touched, { passive: true, capture: true });
    const since = Date.now();
    read ??= readTesterMe();
    void read.then((answer) => {
      if (!live) return;
      if (typeof answer === "string" || answer.state !== "ready") {
        if (answer !== "unavailable") settle();
        return;
      }
      const tryOpen = () => {
        if (!live) return;
        const now = Date.now();
        if (
          now - since >= SETTLE_MS &&
          now - lastTouch >= STILL_MS &&
          document.visibilityState === "visible" &&
          !snoozed(now) &&
          !busyWithTask(document, window.location.href)
        ) {
          // Showing counts: it stays away for a week whether it is closed or not.
          snooze();
          setEmail(answer.email);
          return;
        }
        timer = window.setTimeout(tryOpen, CHECK_EVERY_MS);
      };
      tryOpen();
    });
    return () => {
      live = false;
      window.clearTimeout(timer);
      for (const name of events)
        window.removeEventListener(name, touched, { capture: true });
    };
  }, [pathname]);

  const close = () => {
    snooze();
    setEmail(null);
  };

  return (
    <Sheet
      open={email !== null}
      onClose={close}
      title="Get the Sales X-Ray app"
      description={COPY.sheetText}
      footer={
        <button type="button" className={styles.link} onClick={close}>
          Not now
        </button>
      }
    >
      {email ? <PlaySteps email={email} /> : null}
    </Sheet>
  );
}

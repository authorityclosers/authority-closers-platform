"use client";

/**
 * "Get the Android app" (owner, 13 Nov 2026): a tester who is signed in on an
 * Android phone's browser, not in the app, and whose Google account the team
 * has added to the Play group, gets one big sheet with Play's two steps.
 * Closing it ("Not now", a swipe or back) keeps it away for three days on this
 * phone. It asks the server once per page load, only on the signed-in app's
 * own pages, and not again in this tab once the answer is "not ready".
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
export const SNOOZE_MS = 3 * 24 * 60 * 60 * 1000;

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

export function GetAppSheet() {
  const pathname = usePathname();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (
      !isShellRoute(pathname) ||
      !isAndroidBrowser(navigator.userAgent) ||
      snoozed(Date.now()) ||
      settled()
    )
      return;
    let live = true;
    read ??= readTesterMe();
    void read.then((answer) => {
      if (typeof answer !== "string" && answer.state === "ready") {
        if (live) setEmail(answer.email);
      } else if (answer !== "unavailable") settle();
    });
    return () => {
      live = false;
    };
  }, [pathname]);

  const close = () => {
    try {
      localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS));
    } catch {
      // It closes all the same.
    }
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

"use client";

/**
 * "Get the Android app" (owner, 13 Nov 2026): a tester who is signed in on an
 * Android phone's browser, not in the app, and whose Google account the team
 * has added to the Play group, gets one big sheet with Play's two steps.
 * "Not now" keeps it away for three days on this phone. It asks the server
 * once per tab, and only on the signed-in app's own pages.
 */
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { isShellRoute } from "../app-session";
import { Sheet } from "../ui/sheet";
import { COPY, withEmail } from "./testers-copy";
import { isAndroidBrowser, readTesterMe } from "./testers-client";
import { PlaySteps } from "./testers-page";
import styles from "./testers.module.css";

export const SNOOZE_KEY = "sx.testers.app-sheet";
export const ASKED_KEY = "sx.testers.asked";
export const SNOOZE_MS = 3 * 24 * 60 * 60 * 1000;

function snoozed(now: number): boolean {
  try {
    const until = Number(localStorage.getItem(SNOOZE_KEY) ?? "0");
    return Number.isFinite(until) && until > now;
  } catch {
    return false;
  }
}

function askedThisTab(): boolean {
  try {
    if (sessionStorage.getItem(ASKED_KEY)) return true;
    sessionStorage.setItem(ASKED_KEY, "1");
  } catch {
    // Without storage, asking again on the next page is harmless.
  }
  return false;
}

export function GetAppSheet() {
  const pathname = usePathname();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (
      !isShellRoute(pathname) ||
      !isAndroidBrowser(navigator.userAgent) ||
      snoozed(Date.now()) ||
      askedThisTab()
    )
      return;
    const controller = new AbortController();
    void readTesterMe(controller.signal).then((read) => {
      if (controller.signal.aborted || typeof read === "string") return;
      if (read.state === "ready") setEmail(read.email);
    });
    return () => controller.abort();
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
      description={withEmail(COPY.readyText, email ?? "")}
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

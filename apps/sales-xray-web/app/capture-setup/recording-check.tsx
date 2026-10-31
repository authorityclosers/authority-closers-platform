"use client";

/**
 * "Your call has no recording" (owner, 30 Oct 2026, fix 5: "if a connected call
 * has no recording file after 2 minutes, show the rep a banner with the steps
 * to turn on automatic call recording in their phone's dialer (Xiaomi/HyperOS
 * steps first)").
 *
 * The server counts the seller's connected lead calls today with no recording
 * two minutes after they ended, from the same calls Home counts as Tried
 * (call_ai/missing_recordings.py). It is a corner card in the app's corner
 * stack, never fixed over the page (persona QA and the test robot, 31 Oct
 * 2026), and never on Home, whose Tried row already carries the count:
 * - the day's first sight is the full card: how many, where the Phone app's
 *   switch is, and "See which" to Calls;
 * - after that it is one slim line ("28 calls not recorded"); Details opens the
 *   full card again;
 * - closing either hides it for the rest of the day.
 * It never shows over a setup screen, or when Home tried nothing today.
 */

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { setupStatus, inPhoneApp, onPhoneSignal } from "../leads/native-phone";
import { dismissNotice, notify, type Notice } from "../notice-center";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readMissingRecordings,
  type MissingRecordings,
} from "./capture-setup-client";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";
import { PERMISSIONS_ATTRIBUTE } from "./permissions-rules";

const EVERY_MS = 120_000;
// The full card shows this long the first time each day, then becomes one line.
const FULL_MS = 12_000;
const DAY_KEY = "sx-recording-check-day";
export const RECORDING_NOTICE = "recording-check";
const COVERS = [
  "data-sx-consent",
  PERMISSIONS_ATTRIBUTE,
  CAPTURE_SETUP_ATTRIBUTE,
] as const;
const HOME = new Set(["/", "/dashboard"]);

/** Where the Phone app's switch is, by make: Xiaomi's when the make is unknown. */
const WHERE: Record<string, string> = {
  xiaomi: "Phone, Settings, Call recording: record automatically, all numbers.",
  samsung: "Phone, Settings, Record calls: auto record calls, all calls.",
  vivo: "Phone, Settings, Call recording: auto record all calls.",
  oppo: "Phone, Settings, Call recording: record all calls.",
  realme: "Phone, Settings, Call recording: record all calls.",
  oneplus: "Phone, Settings, Call recording: record all calls.",
};

type DayState = "full_seen" | "closed";

/** Today in India, the day the server counts. */
function today(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

function readDay(): DayState | null {
  try {
    const [day, state] = (window.localStorage.getItem(DAY_KEY) ?? "").split(
      ":",
    );
    return day === today() && (state === "full_seen" || state === "closed")
      ? state
      : null;
  } catch {
    return null;
  }
}

function writeDay(state: DayState) {
  try {
    window.localStorage.setItem(DAY_KEY, `${today()}:${state}`);
  } catch {
    // Without storage the day's first card can show again; closing still hides it now.
  }
}

function watchCovers(changed: () => void) {
  const watch = new MutationObserver(changed);
  watch.observe(document.documentElement, {
    attributes: true,
    attributeFilter: [...COVERS],
  });
  return () => watch.disconnect();
}

const coveredNow = () =>
  COVERS.some((name) => document.documentElement.hasAttribute(name));

/** The full corner card: how many calls, where the Phone app's switch is, See which. */
export function recordingNotice(
  calls: number,
  family: string | null,
  onSeeWhich: () => void,
  onClosed: () => void = () => undefined,
): Notice {
  return {
    id: RECORDING_NOTICE,
    tone: "info",
    title:
      calls === 1
        ? "A call today has no recording"
        : `${calls} calls today have no recording`,
    message: `Turn on call recording: ${WHERE[family ?? ""] ?? WHERE.xiaomi}`,
    action: { label: "See which", run: onSeeWhich, icon: "open" },
    // Stays until closed; closing hides it for the rest of the day.
    onDismiss: async () => onClosed(),
  };
}

/** After the day's first sight: one slim line; Details opens the full card. */
export function recordingLine(
  calls: number,
  onDetails: () => void,
  onClosed: () => void = () => undefined,
): Notice {
  return {
    id: RECORDING_NOTICE,
    tone: "info",
    title: calls === 1 ? "1 call not recorded" : `${calls} calls not recorded`,
    action: { label: "Details", run: onDetails },
    slim: true,
    onDismiss: async () => onClosed(),
  };
}

export function RecordingCheck() {
  const access = useWorkspaceAccess();
  const router = useRouter();
  const pathname = usePathname();
  const ready =
    access?.authenticated === true &&
    access.status === "ready" &&
    access.context !== null;
  const tenant = access?.context?.tenantId ?? "";
  const [missing, setMissing] = useState<MissingRecordings | null>(null);
  const [family, setFamily] = useState<string | null>(null);
  const [day, setDay] = useState<DayState | null>(null);
  const [expanded, setExpanded] = useState(false);

  const read = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    try {
      setMissing(await readMissingRecordings());
    } catch {
      // A failed read shows nothing; the next one tries again.
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    void (async () => {
      const status = inPhoneApp() ? await setupStatus() : null;
      if (!alive) return;
      setFamily(status?.family ?? null);
      setDay(readDay());
      await read();
    })();
    const timer = window.setInterval(() => void read(), EVERY_MS);
    const stop = onPhoneSignal((event) => {
      if (event === "resume") void read();
    });
    return () => {
      alive = false;
      window.clearInterval(timer);
      stop();
    };
  }, [ready, tenant, read]);

  // Never over the Terms card or a setup screen.
  const covered = useSyncExternalStore(watchCovers, coveredNow, () => true);
  const onHome = HOME.has((pathname ?? "/").replace(/\/$/, "") || "/");
  // Never when Home says nothing was tried today: the two always agree.
  const calls = missing?.calls ?? 0;
  const show =
    ready &&
    !covered &&
    !onHome &&
    calls > 0 &&
    (missing?.tried ?? 0) > 0 &&
    day !== "closed";
  const full = show && (day === null || expanded);

  useEffect(() => {
    if (!show) {
      dismissNotice(RECORDING_NOTICE);
      return;
    }
    const close = () => {
      writeDay("closed");
      setDay("closed");
      setExpanded(false);
    };
    notify(
      full
        ? recordingNotice(calls, family, () => router.push("/calls"), close)
        : recordingLine(calls, () => setExpanded(true), close),
    );
    if (!full || day !== null) return;
    // The day's first full card becomes one line after a while.
    const later = window.setTimeout(() => {
      writeDay("full_seen");
      setDay("full_seen");
    }, FULL_MS);
    return () => window.clearTimeout(later);
  }, [show, full, calls, family, day, router]);

  useEffect(() => () => dismissNotice(RECORDING_NOTICE), []);

  return null;
}

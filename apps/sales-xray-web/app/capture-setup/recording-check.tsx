"use client";

/**
 * "Your call has no recording" (owner, 30 Oct 2026, fix 5: "if a connected call
 * has no recording file after 2 minutes, show the rep a banner with the steps
 * to turn on automatic call recording in their phone's dialer (Xiaomi/HyperOS
 * steps first)").
 *
 * The server counts the seller's connected lead calls today with no recording
 * two minutes after they ended (call_ai/missing_recordings.py). The card shows
 * this phone's Phone-app steps when the app knows the phone's make, else
 * Xiaomi's first, and in the app it opens the call recording settings. Done
 * hides it until another call is missing. It waits while a setup screen covers
 * the page, and reads again on return to the app and every two minutes.
 */

import { MicOff } from "lucide-react";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { RECORDER_STEPS, recorderSteps } from "../leads/phone-setup-words";
import {
  inPhoneApp,
  onPhoneSignal,
  setupOpen,
  setupStatus,
} from "../leads/native-phone";
import { Button } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readMissingRecordings,
  type MissingRecordings,
} from "./capture-setup-client";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";
import own from "./capture-setup.module.css";
import { PERMISSIONS_ATTRIBUTE } from "./permissions-rules";
import { named } from "./product-name";

const EVERY_MS = 120_000;
const SEEN_KEY = "sx-recording-check-seen";
const COVERS = [
  "data-sx-consent",
  PERMISSIONS_ATTRIBUTE,
  CAPTURE_SETUP_ATTRIBUTE,
] as const;

const BRANDS: Record<string, string> = {
  xiaomi: "Xiaomi, Redmi and POCO (HyperOS)",
  samsung: "Samsung",
  vivo: "Vivo",
  oppo: "Oppo",
  realme: "Realme",
  oneplus: "OnePlus",
  huawei: "Huawei",
};

function seen(): string | null {
  try {
    return window.sessionStorage.getItem(SEEN_KEY);
  } catch {
    return null;
  }
}

function markSeen(latest: string) {
  try {
    window.sessionStorage.setItem(SEEN_KEY, latest);
  } catch {
    // Without storage the card can show again on the next read; Done still closes it.
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

/** The card itself, for the banner and the review fixture. */
export function RecordingCheckCard({
  calls,
  family,
  inApp,
  onOpen,
  onDone,
}: {
  calls: number;
  /** The phone's make when the app knows it; Xiaomi's steps otherwise. */
  family: string | null;
  inApp: boolean;
  onOpen: () => void;
  onDone: () => void;
}) {
  const brand =
    family && family !== "other" && Object.hasOwn(RECORDER_STEPS, family)
      ? family
      : "xiaomi";
  return (
    <aside
      className={own.check}
      role="status"
      aria-label="Calls without a recording"
    >
      <span className={own.checkIcon}>
        <MicOff size={20} aria-hidden="true" />
      </span>
      <div className={own.checkBody}>
        <strong>
          {calls === 1
            ? "A call today has no recording"
            : `${calls} calls today have no recording`}
        </strong>
        <small>
          Your Phone app didn&apos;t save {calls === 1 ? "it" : "them"}. Turn on
          automatic call recording so every call gets its report.
        </small>
        <b className={own.checkBrand}>On {BRANDS[brand] ?? "your phone"}:</b>
        <ol className={own.checkSteps}>
          {recorderSteps(brand).map((line) => (
            <li key={line}>{named(line)}</li>
          ))}
        </ol>
        {brand === "xiaomi" && !family ? (
          <small>
            Other phones: open the Phone app&apos;s settings and turn on call
            recording for all calls.
          </small>
        ) : null}
        <div className={own.checkActions}>
          {inApp ? (
            <Button variant="primary" onClick={onOpen}>
              Open call recording settings
            </Button>
          ) : null}
          <Button variant="ghost" onClick={onDone}>
            Done
          </Button>
        </div>
      </div>
    </aside>
  );
}

export function RecordingCheck() {
  const access = useWorkspaceAccess();
  const ready =
    access?.authenticated === true &&
    access.status === "ready" &&
    access.context !== null;
  const tenant = access?.context?.tenantId ?? "";
  const [missing, setMissing] = useState<MissingRecordings | null>(null);
  const [family, setFamily] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const read = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const next = await readMissingRecordings();
      setMissing(next);
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
      setDone(seen());
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

  if (
    !ready ||
    covered ||
    !missing?.calls ||
    !missing.latest_at ||
    done === missing.latest_at
  )
    return null;
  const latest = missing.latest_at;
  return (
    <RecordingCheckCard
      calls={missing.calls}
      family={family}
      inApp={inPhoneApp()}
      onOpen={() => void setupOpen("recorder")}
      onDone={() => {
        markSeen(latest);
        setDone(latest);
      }}
    />
  );
}

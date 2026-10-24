"use client";

/**
 * Phone setup (UX study item 7: Privyr's Getting Started bar, TeleCRM's and
 * Callyzer's permission screens). Inside the Sales Xray phone app a bar sits
 * at the top of Leads until the phone is ready ("Phone setup · 5 of 9 done").
 * It opens a checklist with one line per need, ticked green when done. A
 * permission line first says what Sales Xray reads, what leaves the phone and
 * why, and only then asks Android. The checklist goes to Sales Xray so a
 * manager sees each seller's phone on Team. Nothing shows in a browser or in
 * an older app.
 */

import { CheckCircle2, ChevronRight, Circle, Smartphone } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { Sheet } from "./sheet-frame";
import { usePhoneOnboarded } from "./phone-onboarding";
import { reportPhone } from "./leads-client";
import {
  inPhoneApp,
  onPhoneSignal,
  setupStatus,
  type SetupStatus,
} from "./native-phone";
import { PhoneSetupFlow, type FlowStep } from "./phone-setup-flow";
import {
  FOLDER_TODO,
  CHECK_ORDER,
  CHECK_TODO,
  checkLabel,
  HIDDEN_TODO,
  TRUECALLER_NOTE,
  type PhoneCheck,
} from "./phone-setup-words";
import styles from "./leads.module.css";

const REPORT_KEY = "sx-leads-phone-report";
const REPORT_EVERY_MS = 6 * 60 * 60 * 1000;

/** Xiaomi's hidden recordings folder: the Call recordings line asks for All files access (#49). */
export function needsAllFiles(status: SetupStatus): boolean {
  return status.needsAllFiles && status.allFilesSupported;
}

/** The same in the Play build, which has no All files access: the seller picks the folder (S8). */
export function needsFolderPick(status: SetupStatus): boolean {
  return (
    status.needsAllFiles &&
    !status.allFilesSupported &&
    status.folderPickSupported
  );
}

/** What a line says while it is not done yet, for this phone. */
export function lineTodo(key: PhoneCheck, status: SetupStatus): string {
  if (key === "recordings" && needsAllFiles(status)) return HIDDEN_TODO;
  if (key === "recordings" && needsFolderPick(status)) return FOLDER_TODO;
  return CHECK_TODO[key];
}

/**
 * The lines this phone shows: Autostart only on brands that have it, and work-call
 * logging only in an app build that can read the call history (not the Play build).
 */
export function setupLines(status: SetupStatus): PhoneCheck[] {
  return CHECK_ORDER.filter(
    (key) =>
      (key !== "autostart" || status.autostartNeeded) &&
      (key !== "callLog" || status.callLogSupported),
  );
}

export function setupProgress(status: SetupStatus): {
  done: number;
  total: number;
} {
  const lines = setupLines(status);
  return {
    done: lines.filter((key) => status.checks[key] === true).length,
    total: lines.length,
  };
}

/** Sends the checklist when it changed, or every few hours, so Team stays current. */
export async function reportSetup(status: SetupStatus): Promise<void> {
  if (!status.device) return;
  const sign = JSON.stringify([status.device, status.version, status.checks]);
  try {
    const last = JSON.parse(localStorage.getItem(REPORT_KEY) ?? "null") as {
      sign?: string;
      at?: number;
    } | null;
    if (last?.sign === sign && Date.now() - (last.at ?? 0) < REPORT_EVERY_MS)
      return;
  } catch {
    // Storage blocked: send it.
  }
  try {
    await reportPhone({
      device_id: status.device,
      app_version: status.version || undefined,
      family: status.family,
      checks: status.checks,
    });
    try {
      localStorage.setItem(
        REPORT_KEY,
        JSON.stringify({ sign, at: Date.now() }),
      );
    } catch {
      // Storage blocked: sent again next time.
    }
  } catch {
    // Offline or signed out: sent next time.
  }
}

/** Opens the checklist from More (/leads#phone-setup) after the first run. */
export const PHONE_SETUP_HASH = "#phone-setup";

export function PhoneSetupBar() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [open, setOpen] = useState(false);
  // "Set up this phone": the bar starts the guided flow, at the first thing to do.
  const [flow, setFlow] = useState(false);
  // The first run asked for each permission: the bar leaves Leads, the
  // checklist stays one tap away in More.
  const onboarded = usePhoneOnboarded();

  useEffect(() => {
    const read = () => {
      if (window.location.hash === PHONE_SETUP_HASH) setOpen(true);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  const take = useCallback((next: SetupStatus | null) => {
    if (!next) return;
    setStatus(next);
    void reportSetup(next);
  }, []);

  useEffect(() => {
    if (!inPhoneApp()) return;
    void setupStatus().then(take);
    // Back from a settings screen, or new calls logged: look again.
    return onPhoneSignal((event) => {
      if (event === "resume" || event === "calls")
        void setupStatus().then(take);
    });
  }, [take]);

  if (!status) return null;
  const { done, total } = setupProgress(status);
  if ((done >= total || onboarded) && !open && !flow) return null;

  return (
    <>
      <button
        type="button"
        className={styles.setupBar}
        onClick={() => setFlow(true)}
      >
        <Smartphone size={18} aria-hidden="true" />
        <span className={styles.setupBarText}>
          <strong>Phone setup</strong>
          <small>
            {done} of {total} done
          </small>
        </span>
        <span className={styles.setupTrack} aria-hidden="true">
          <i style={{ width: `${(done / total) * 100}%` }} />
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </button>
      {flow ? (
        <PhoneSetupFlow
          onClose={(next) => {
            setFlow(false);
            take(next);
          }}
        />
      ) : null}
      <PhoneSetupSheet
        open={open}
        status={status}
        onStatus={take}
        onClose={() => {
          setOpen(false);
          if (window.location.hash === PHONE_SETUP_HASH)
            history.replaceState(
              null,
              "",
              window.location.pathname + window.location.search,
            );
        }}
      />
    </>
  );
}

/** The lines the guided flow can set up from the checklist. */
export const FIXABLE = new Set<PhoneCheck>([
  "calls",
  "recordings",
  "notifications",
  "recorder",
  "battery",
  "autostart",
  "callLog",
]);

/**
 * The checklist: one line per need, ticked when done. A line's Set up opens
 * the guided flow for that one thing (phone-setup-flow.tsx), which says what
 * Sales X-Ray reads and why before Android asks.
 */
export function PhoneSetupSheet({
  open,
  status,
  onStatus,
  onClose,
}: {
  open: boolean;
  status: SetupStatus;
  onStatus: (next: SetupStatus | null) => void;
  onClose: () => void;
}) {
  const [fix, setFix] = useState<FlowStep | null>(null);
  const { done, total } = setupProgress(status);

  // Back from Android's settings with a line done: the list shows it.
  useEffect(() => {
    if (!open) return;
    return onPhoneSignal((event) => {
      if (event === "resume") void setupStatus().then(onStatus);
    });
  }, [open, onStatus]);

  return (
    <>
      <Sheet open={open} label="Phone setup" onClose={onClose}>
        <div className={styles.setupSheet}>
          <header className={styles.setupHead}>
            <h2>Phone setup</h2>
            <p>
              {done} of {total} done
            </p>
            <span className={styles.setupTrack} aria-hidden="true">
              <i style={{ width: `${(done / total) * 100}%` }} />
            </span>
          </header>
          <ol className={styles.setupList} aria-label="Phone setup">
            {setupLines(status).map((key) => {
              const ok = status.checks[key] === true;
              return (
                <li key={key} data-done={ok || undefined}>
                  {ok ? (
                    <CheckCircle2 size={20} aria-label="Done" />
                  ) : (
                    <Circle size={20} aria-label="To do" />
                  )}
                  <span>
                    <strong>{checkLabel(key, status.store)}</strong>
                    <small>{ok ? "Done" : lineTodo(key, status)}</small>
                  </span>
                  {!ok && FIXABLE.has(key) ? (
                    <Button onClick={() => setFix(key as FlowStep)}>
                      Set up
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ol>
          {status.truecaller ? (
            <p className={styles.hint}>{TRUECALLER_NOTE}</p>
          ) : null}
          <p className={styles.hint}>
            Your manager sees which lines are done. Never your calls with other
            numbers.
          </p>
        </div>
      </Sheet>
      {fix ? (
        <PhoneSetupFlow
          only={fix}
          onClose={(next) => {
            setFix(null);
            onStatus(next);
          }}
        />
      ) : null}
    </>
  );
}

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
  askCallAccess,
  askNotifications,
  askRecordingAccess,
  buzz,
  callLogSetup,
  callLogStatus,
  inPhoneApp,
  onPhoneSignal,
  setupMark,
  recorderOpen,
  setupOpen,
  setupStatus,
  type CallLogStatus,
  type SetupStatus,
} from "./native-phone";
import {
  ALL_FILES_EXPLAINER,
  CHECK_ORDER,
  CHECK_TODO,
  checkLabel,
  explainerFor,
  HIDDEN_TODO,
  recorderGuide,
  TRUECALLER_NOTE,
  type PhoneCheck,
} from "./phone-setup-words";
import styles from "./leads.module.css";

const REPORT_KEY = "sx-leads-phone-report";
const REPORT_EVERY_MS = 6 * 60 * 60 * 1000;
const ACTIONS = new Set<PhoneCheck>([
  "calls",
  "recordings",
  "notifications",
  "recorder",
  "battery",
  "autostart",
  "callLog",
]);

/** Xiaomi's hidden recordings folder: the Call recordings line asks for All files access (#49). */
export function needsAllFiles(status: SetupStatus): boolean {
  return status.needsAllFiles && status.allFilesSupported;
}

/** What a line says while it is not done yet, for this phone. */
export function lineTodo(key: PhoneCheck, status: SetupStatus): string {
  if (key === "recordings" && needsAllFiles(status)) return HIDDEN_TODO;
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
  if ((done >= total || onboarded) && !open) return null;

  return (
    <>
      <button
        type="button"
        className={styles.setupBar}
        onClick={() => setOpen(true)}
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
  const [view, setView] = useState<PhoneCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [log, setLog] = useState<CallLogStatus | null>(null);
  const [sim, setSim] = useState("");
  const { done, total } = setupProgress(status);
  const guide = recorderGuide(status.recorder, status.family);

  // Back from Android's settings (All files access) with the line done: back to the list.
  useEffect(() => {
    if (!open) return;
    return onPhoneSignal((event) => {
      if (event !== "resume") return;
      void setupStatus().then((next) => {
        if (!next) return;
        onStatus(next);
        setView((current) =>
          current && next.checks[current] ? null : current,
        );
      });
    });
  }, [open, onStatus]);

  const show = async (key: PhoneCheck) => {
    setNote(null);
    setView(key);
    if (key === "callLog") {
      const next = await callLogStatus();
      setLog(next);
      setSim(next?.sim || next?.sims[0]?.id || "");
    }
  };

  /** Does the line's job, reads the checklist again and goes back to it. */
  const run = async (key: PhoneCheck, job: () => Promise<unknown>) => {
    setBusy(true);
    setNote(null);
    try {
      await job();
      const next = await setupStatus();
      onStatus(next);
      if (next?.checks[key]) {
        buzz("done");
        setView(null);
      } else if (
        key !== "battery" &&
        key !== "recorder" &&
        key !== "autostart" &&
        !(key === "recordings" && needsAllFiles(status))
      )
        setNote(
          "Not allowed yet. You can allow it in your phone's settings for Sales X-Ray.",
        );
    } finally {
      setBusy(false);
    }
  };

  const allow = (key: PhoneCheck) => {
    switch (key) {
      case "calls":
        return run(key, () => askCallAccess().catch(() => false));
      case "recordings":
        // Android's All files access screen opens; the line ticks when the seller comes back.
        return needsAllFiles(status)
          ? run(key, () => setupOpen("allFiles"))
          : run(key, askRecordingAccess);
      case "notifications":
        return run(key, askNotifications);
      case "battery":
        // Android's own screen opens; the line ticks when the seller comes back.
        return run(key, () => setupOpen("battery"));
      default:
        return Promise.resolve();
    }
  };

  const explainer =
    view === "recordings" && needsAllFiles(status)
      ? ALL_FILES_EXPLAINER
      : view
        ? explainerFor(view, status.store)
        : undefined;

  return (
    <Sheet
      open={open}
      label="Phone setup"
      onClose={() => {
        setView(null);
        onClose();
      }}
    >
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

        {view === null ? (
          <>
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
                    {!ok && ACTIONS.has(key) ? (
                      <Button onClick={() => void show(key)}>Set up</Button>
                    ) : null}
                  </li>
                );
              })}
            </ol>
            {status.truecaller ? (
              <p className={styles.hint}>{TRUECALLER_NOTE}</p>
            ) : null}
            <p className={styles.hint}>
              Your manager sees which lines are done. Never your calls with
              other numbers.
            </p>
          </>
        ) : (
          <section
            className={styles.setupView}
            aria-label={checkLabel(view, status.store)}
          >
            <h3>{checkLabel(view, status.store)}</h3>
            {explainer ? (
              <dl>
                <div>
                  <dt>What Sales X-Ray reads</dt>
                  <dd>{explainer.reads}</dd>
                </div>
                <div>
                  <dt>What leaves your phone</dt>
                  <dd>{explainer.sends}</dd>
                </div>
                <div>
                  <dt>Why</dt>
                  <dd>{explainer.why}</dd>
                </div>
              </dl>
            ) : null}
            {view === "recorder" ? (
              <>
                {guide.lead ? <p>{guide.lead}</p> : null}
                <ol className={styles.setupSteps}>
                  {guide.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </>
            ) : null}
            {view === "autostart" ? (
              <p>
                Your phone stops apps that start by themselves. Find Sales X-Ray
                in the list and switch it on, then come back.
              </p>
            ) : null}
            {view === "callLog" ? (
              <>
                <p>
                  {CHECK_TODO.callLog} Other numbers never leave your phone.
                </p>
                {log && log.sims.length > 1 ? (
                  <div
                    className={styles.phoneLogSims}
                    role="group"
                    aria-label="Work SIM"
                  >
                    <span>Work SIM</span>
                    {log.sims.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={styles.chip}
                        aria-pressed={sim === item.id}
                        onClick={() => setSim(item.id)}
                      >
                        {item.label || "SIM"}
                      </button>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}
            {note ? (
              <p className={styles.error} role="alert">
                {note}
              </p>
            ) : null}
            <div className={styles.row}>
              {explainer ? (
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => void allow(view)}
                >
                  {explainer.allow}
                </Button>
              ) : null}
              {view === "recorder" && guide.closed ? (
                status.recorder?.switchTo ? (
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() => void recorderOpen("defaultDialer")}
                  >
                    Choose the Phone app
                  </Button>
                ) : null
              ) : view === "recorder" ? (
                <>
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() => void setupOpen("recorder")}
                  >
                    Open call recording settings
                  </Button>
                  {status.recorder?.recording === "on" ? null : (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void run("recorder", () => setupMark("recorder", true))
                      }
                    >
                      It&apos;s on
                    </Button>
                  )}
                </>
              ) : null}
              {view === "autostart" ? (
                <>
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() => void setupOpen("autostart")}
                  >
                    Open Autostart
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void run("autostart", () => setupMark("autostart", true))
                    }
                  >
                    Done
                  </Button>
                </>
              ) : null}
              {view === "callLog" ? (
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() =>
                    void run("callLog", () => callLogSetup(true, sim))
                  }
                >
                  Turn on
                </Button>
              ) : null}
              <Button variant="ghost" onClick={() => setView(null)}>
                Not now
              </Button>
            </div>
          </section>
        )}
      </div>
    </Sheet>
  );
}

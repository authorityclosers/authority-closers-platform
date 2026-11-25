"use client";

/**
 * "Your call wasn't checked" (owner, 17 Nov 2026 app review: "upload/analysis
 * required", asked again after a call with no upload). When the phone saw a
 * lead call end and nothing uploaded within ten minutes because uploads are
 * off here, the app names the call and turns uploads on one step at a time
 * (upload notices, the recordings folder, uploads), each with its purpose.
 * Turning uploads on shows Android's own consent words and, when calls were
 * saved while uploads were off, asks whether to upload those too: the choice
 * stays the seller's, never made for them. The missed-alert card's pattern and
 * look; shown once per call on this phone, never in a browser, never over the
 * call capture setup. Words and rules: upload-reask-rules.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { readMissingRecordings } from "../capture-setup/capture-setup-client";
import { openCaptureSetup } from "../capture-setup/capture-setup-gate";
import { CAPTURE_SETUP_ATTRIBUTE } from "../capture-setup/capture-setup-rules";
import {
  askNotifications,
  autoCaptureSetup,
  autoCaptureStatus,
  inPhoneApp,
  pickRecordingsFolder,
  setupOpen,
  setupStatus,
} from "../leads/native-phone";
import { track } from "../telemetry";
import {
  UPLOAD_STEP_WORDS,
  headline,
  markShown,
  readShown,
  uncheckedCall,
  uploadStepsLeft,
  uploadsOffHere,
  type UncheckedCall,
  type UploadStep,
} from "./upload-reask-rules";
import styles from "./missed-alert.module.css";
import own from "./upload-reask.module.css";

/** How often the server is asked again while the app stays open. */
const LOOK_EVERY_MS = 2 * 60 * 1000;

type Stage =
  | { at: "card" }
  | {
      at: "step";
      steps: UploadStep[];
      index: number;
      busy: boolean;
      note: string | null;
    }
  | { at: "done"; on: boolean };

function firstName(name: string): string {
  return name.split(/\s+/)[0] || name;
}

function initials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  return (
    (
      (words[0]?.[0] ?? "") +
      (words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "")
    ).toUpperCase() || "?"
  );
}

function feature(name: string) {
  try {
    track("sx.feature_used", { feature: name });
  } catch {
    // Telemetry never stops the card.
  }
}

/** Another full-screen step is up: the setup, or the missed-alert card. */
function somethingElseUp(): boolean {
  return (
    document.documentElement.hasAttribute(CAPTURE_SETUP_ATTRIBUTE) ||
    document.querySelector("dialog[data-missed-alert][open]") !== null
  );
}

function UploadOff() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={styles.bellGlyph}>
      <path d="M10 22h-1a5 5 0 0 1-.6-10A7 7 0 0 1 21.7 10" />
      <path d="M24 13.3A4.5 4.5 0 0 1 23 22h-2" />
      <path d="M16 26v-9m-3.5 3.5L16 17l3.5 3.5" />
      <path d="M6 6l20 20" className={styles.bellSlash} />
    </svg>
  );
}

function DrawnCheck() {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className={styles.check}>
      <circle cx="32" cy="32" r="28" className={styles.checkRing} />
      <path d="M20 33l8 8 16-17" className={styles.checkMark} />
    </svg>
  );
}

export function UploadReask({
  accountKey,
  openLead,
}: {
  accountKey: string | null;
  openLead: (href: string) => void;
}) {
  const [call, setCall] = useState<UncheckedCall | null>(null);
  const [stage, setStage] = useState<Stage>({ at: "card" });
  const [wifiOnly, setWifiOnly] = useState(false);
  const checking = useRef(false);
  const lastLook = useRef(0);

  // Look when the app opens, when it comes back, and every two minutes while open.
  useEffect(() => {
    if (!accountKey || call || !inPhoneApp()) return;
    const look = () => {
      if (checking.current || document.visibilityState !== "visible") return;
      if (Date.now() - lastLook.current < LOOK_EVERY_MS) return;
      if (somethingElseUp()) return;
      checking.current = true;
      lastLook.current = Date.now();
      void (async () => {
        const status = await autoCaptureStatus();
        if (!uploadsOffHere(status)) return;
        const missing = await readMissingRecordings().catch(() => null);
        if (!missing) return;
        const found = uncheckedCall(
          missing.items,
          Date.now(),
          readShown(accountKey),
        );
        if (!found) return;
        if (somethingElseUp()) {
          // The setup came up meanwhile: look again as soon as it is gone.
          lastLook.current = 0;
          return;
        }
        markShown(accountKey, found.callIds);
        feature("upload_reask_shown");
        setWifiOnly(status?.wifiOnly === true);
        setStage({ at: "card" });
        setCall(found);
      })().finally(() => {
        checking.current = false;
      });
    };
    look();
    const timer = window.setInterval(look, LOOK_EVERY_MS);
    document.addEventListener("visibilitychange", look);
    // The setup decided or closed: look then, not two minutes later.
    const html = document.documentElement;
    const watch = new MutationObserver(() => {
      if (!html.hasAttribute(CAPTURE_SETUP_ATTRIBUTE)) look();
    });
    watch.observe(html, {
      attributes: true,
      attributeFilter: [CAPTURE_SETUP_ATTRIBUTE],
    });
    return () => {
      window.clearInterval(timer);
      watch.disconnect();
      document.removeEventListener("visibilitychange", look);
    };
  }, [accountKey, call]);

  const close = useCallback(() => setCall(null), []);

  const finish = useCallback(async () => {
    const status = await autoCaptureStatus();
    const on = status?.on === true;
    if (on) feature("upload_reask_on");
    setStage({ at: "done", on });
  }, []);

  const start = useCallback(async () => {
    feature("upload_reask_started");
    const setup = await setupStatus();
    const steps = uploadStepsLeft({
      notifications: setup?.checks.notifications === true,
      folderPicked: setup?.folderPicked === true,
    });
    setStage({ at: "step", steps, index: 0, busy: false, note: null });
  }, []);

  const next = useCallback(
    (steps: UploadStep[], index: number) => {
      if (index + 1 >= steps.length) return void finish();
      setStage({
        at: "step",
        steps,
        index: index + 1,
        busy: false,
        note: null,
      });
    },
    [finish],
  );

  const allow = useCallback(
    async (steps: UploadStep[], index: number) => {
      const step = steps[index];
      if (!step) return;
      setStage({ at: "step", steps, index, busy: true, note: null });
      try {
        if (step === "notices") {
          const setup = await setupStatus();
          if (setup?.blocked.notifications) await setupOpen("notifications");
          else await askNotifications();
        } else if (step === "folder") {
          await pickRecordingsFolder();
        } else {
          // Android shows the consent words with Turn on and Not now, then,
          // for calls saved while uploads were off, Upload them or Skip them.
          await autoCaptureSetup(true, wifiOnly);
        }
      } catch (reason) {
        const code = reason instanceof Error ? reason.message : "";
        if (
          step === "uploads" &&
          (code === "standing_consent_required" || code === "profile_required")
        ) {
          // The seller's own agreement comes first: the setup asks it afresh.
          close();
          openCaptureSetup("uploads");
          return;
        }
        if (step === "uploads") {
          setStage({
            at: "step",
            steps,
            index,
            busy: false,
            note: "Uploads didn't turn on. Check that the folder is still chosen, then try again.",
          });
          return;
        }
        // An old app or a refused ask: on to the next step, never stuck.
      }
      next(steps, index);
    },
    [close, next, wifiOnly],
  );

  // A modal dialog opened last sits above the page; Escape closes it like the X.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = frame.current;
    if (!call || !dialog || dialog.open) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }, [call]);

  if (!call) return null;
  const name = call.name;
  const named = name !== "your lead";
  const openIt = () => {
    close();
    openLead(call.href);
  };

  return (
    <dialog
      ref={frame}
      className={styles.scrim}
      data-upload-reask=""
      aria-labelledby="upload-reask-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <section className={styles.sheet}>
        <span className={styles.handle} aria-hidden="true" />
        {stage.at === "card" ? (
          <div className={styles.card} key="card">
            <button
              type="button"
              className={styles.close}
              aria-label="Close"
              onClick={close}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
            <div className={styles.cardTop}>
              <span className={styles.bell}>
                <span className={styles.pulse} aria-hidden="true" />
                <UploadOff />
              </span>
              <div className={styles.cardWords}>
                <span className={styles.kicker}>Call not checked</span>
                <h2 id="upload-reask-title" className={styles.headline}>
                  {headline(call)}
                </h2>
              </div>
            </div>
            <div className={styles.leadRow}>
              <span className={styles.avatar} aria-hidden="true">
                {named ? initials(name) : "?"}
              </span>
              <span className={styles.leadWords}>
                <span className={styles.leadName}>
                  {named ? name : "A lead call"}
                </span>
                {call.detail ? (
                  <span className={styles.leadDetail}>{call.detail}</span>
                ) : null}
              </span>
            </div>
            <p className={styles.body}>
              Uploads are off on this phone, so the call never reached analysis.
              Turn them on so every call with a lead is checked.
            </p>
            <button
              type="button"
              className={styles.primary}
              onClick={() => void start()}
            >
              Turn uploads on
            </button>
            <button
              type="button"
              className={styles.textButton}
              onClick={openIt}
            >
              {named ? `Open ${firstName(name)}’s lead` : "Open the lead"}
            </button>
          </div>
        ) : null}

        {stage.at === "step" ? (
          <div className={styles.step} key={`step-${stage.steps[stage.index]}`}>
            {(() => {
              const step = stage.steps[stage.index] ?? "uploads";
              const words = UPLOAD_STEP_WORDS[step];
              const total = stage.steps.length;
              return (
                <>
                  <p className={styles.stepCount}>
                    Step {stage.index + 1} of {total}
                  </p>
                  <div className={styles.progress} aria-hidden="true">
                    {stage.steps.map((s, i) => (
                      <span
                        key={s}
                        className={styles.segment}
                        data-state={
                          i < stage.index
                            ? "done"
                            : i === stage.index
                              ? "now"
                              : "next"
                        }
                      />
                    ))}
                  </div>
                  <span
                    className={`${styles.stepGlyph} ${own[step]}`}
                    data-step={step}
                    aria-hidden="true"
                  />
                  <h2 id="upload-reask-title" className={styles.stepTitle}>
                    {words.title}
                  </h2>
                  <p className={styles.stepWhy}>{words.why}</p>
                  <p className={styles.hint}>Android will ask you next.</p>
                  {stage.note ? (
                    <p className={styles.hint} role="status">
                      {stage.note}
                    </p>
                  ) : null}
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={stage.busy}
                    onClick={() => void allow(stage.steps, stage.index)}
                  >
                    {words.button}
                  </button>
                  <button
                    type="button"
                    className={styles.textButton}
                    disabled={stage.busy}
                    onClick={() => next(stage.steps, stage.index)}
                  >
                    Skip for now
                  </button>
                </>
              );
            })()}
          </div>
        ) : null}

        {stage.at === "done" ? (
          <div className={styles.done} key="done">
            {stage.on ? (
              <>
                <DrawnCheck />
                <h2 id="upload-reask-title" className={styles.doneTitle}>
                  Uploads are on
                </h2>
                <p className={styles.doneWhy}>
                  Your calls with leads upload by themselves and are analysed.
                </p>
              </>
            ) : (
              <>
                <h2 id="upload-reask-title" className={styles.doneTitle}>
                  Uploads are still off
                </h2>
                <p className={styles.doneWhy}>
                  Calls stay on your phone and aren&rsquo;t checked. Turn
                  uploads on any time in Settings.
                </p>
                <button
                  type="button"
                  className={styles.secondary}
                  onClick={() => void start()}
                >
                  Try again
                </button>
              </>
            )}
            <button type="button" className={styles.primary} onClick={openIt}>
              {named ? `Open ${firstName(name)}’s lead` : "Open the lead"}
            </button>
          </div>
        ) : null}
      </section>
    </dialog>
  );
}

"use client";

/**
 * "Missed alert, come back" (owner, 17 Nov 2026): when a new lead reached this
 * person's bell while this phone's notifications were off, the app says so the
 * moment it opens, names the lead, and one tap walks through setup one step at
 * a time (notifications, phone and call log, music and audio, battery), each
 * with its purpose, ending on "All set" and then the lead. Shown once per lead
 * line on this phone; never in a browser. Words and rules: missed-alert-rules.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  askCallAccess,
  askNotifications,
  askRecordingAccess,
  inPhoneApp,
  phoneStatus,
  setupOpen,
  setupStatus,
} from "../leads/native-phone";
import { keepPushAddress } from "./push-keeper";
import {
  STEP_WORDS,
  markShown,
  missedLead,
  phoneMissedIt,
  readShown,
  stepsLeft,
  type MissedLead,
  type PhoneFacts,
  type SetupStep,
} from "./missed-alert-rules";
import type { UpdateNotification } from "./updates-client";
import styles from "./missed-alert.module.css";

async function readFacts(): Promise<PhoneFacts | null> {
  const [setup, status] = await Promise.all([setupStatus(), phoneStatus()]);
  if (!setup || !status) return null;
  return {
    notifications: setup.checks.notifications === true,
    callAccess: status.callAccess === true,
    audio: status.audio === true,
    battery: setup.checks.battery === true,
  };
}

/** Asks Android for one step; true when it opened Android's own screen. */
async function runStep(step: SetupStep): Promise<boolean> {
  try {
    return await askFor(step);
  } catch {
    // An old app or a refused ask: the card goes on to the next step, never stuck.
    return false;
  }
}

async function askFor(step: SetupStep): Promise<boolean> {
  switch (step) {
    case "notifications":
      await askNotifications();
      return false;
    case "phone":
      await askCallAccess();
      return false;
    case "audio":
      await askRecordingAccess();
      return false;
    case "battery":
      // Android's own screen: the card reads again when the person comes back.
      return setupOpen("battery");
  }
}

type Stage =
  | { at: "card" }
  | { at: "step"; steps: SetupStep[]; index: number; busy: boolean }
  | { at: "done"; facts: PhoneFacts | null };

const ALL_STEPS: SetupStep[] = ["notifications", "phone", "audio", "battery"];

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

function BellOff() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={styles.bellGlyph}>
      <path d="M10 23h12l-1.6-2.4V14a4.4 4.4 0 0 0-1.1-2.9" />
      <path d="M17.4 8.3A5 5 0 0 0 11.6 13v7.6L10 23" />
      <path d="M14 26a2.2 2.2 0 0 0 4 0" />
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

export function MissedAlert({
  lines,
  ready,
  accountKey,
  openLead,
}: {
  lines: readonly UpdateNotification[];
  ready: boolean;
  accountKey: string | null;
  openLead: (href: string) => void;
}) {
  const [lead, setLead] = useState<MissedLead | null>(null);
  const [stage, setStage] = useState<Stage>({ at: "card" });
  const checking = useRef(false);

  // Look once the bell has its lines, and again whenever the app comes back.
  useEffect(() => {
    if (!accountKey || !ready || lead || !inPhoneApp()) return;
    const look = () => {
      if (checking.current || document.visibilityState !== "visible") return;
      const found = missedLead(lines, Date.now(), readShown(accountKey));
      if (!found) return;
      checking.current = true;
      void readFacts()
        .then((facts) => {
          if (!phoneMissedIt(facts)) return;
          markShown(accountKey, found.lineId);
          setStage({ at: "card" });
          setLead(found);
        })
        .finally(() => {
          checking.current = false;
        });
    };
    look();
    document.addEventListener("visibilitychange", look);
    return () => document.removeEventListener("visibilitychange", look);
  }, [accountKey, ready, lines, lead]);

  const close = useCallback(() => setLead(null), []);

  const finish = useCallback(async () => {
    const facts = await readFacts();
    if (facts?.notifications && accountKey) await keepPushAddress(accountKey);
    setStage({ at: "done", facts });
  }, [accountKey]);

  const start = useCallback(async () => {
    const facts = await readFacts();
    const steps = facts ? stepsLeft(facts) : ["notifications" as SetupStep];
    if (steps.length === 0) return void finish();
    setStage({ at: "step", steps, index: 0, busy: false });
  }, [finish]);

  const next = useCallback(
    (steps: SetupStep[], index: number) => {
      if (index + 1 >= steps.length) return void finish();
      setStage({ at: "step", steps, index: index + 1, busy: false });
    },
    [finish],
  );

  const allow = useCallback(
    async (steps: SetupStep[], index: number) => {
      const step = steps[index];
      if (!step) return;
      setStage({ at: "step", steps, index, busy: true });
      const left = await runStep(step);
      if (left) {
        // Back from Android's battery screen: go on when the app is in front
        // again (or at once if Android never took the screen).
        let away = document.visibilityState !== "visible";
        let gone = false;
        const go = () => {
          if (gone) return;
          gone = true;
          document.removeEventListener("visibilitychange", back);
          window.clearTimeout(timer);
          next(steps, index);
        };
        const back = () => {
          if (document.visibilityState !== "visible") away = true;
          else if (away) go();
        };
        const timer = window.setTimeout(() => {
          if (!away) go();
        }, 3_000);
        document.addEventListener("visibilitychange", back);
        return;
      }
      next(steps, index);
    },
    [next],
  );

  // A modal dialog opened last sits above every other one, so the card shows
  // over the permissions page too (its Notifications step has no Not now, so
  // it is always up while alerts are off). Escape closes it like the X.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = frame.current;
    if (!lead || !dialog || dialog.open) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }, [lead]);

  if (!lead) return null;
  const name = lead.name;
  const openIt = () => {
    close();
    openLead(lead.href);
  };

  return (
    <dialog
      ref={frame}
      className={styles.scrim}
      data-missed-alert=""
      aria-labelledby="missed-alert-title"
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
                <BellOff />
              </span>
              <div className={styles.cardWords}>
                <span className={styles.kicker}>Missed alert</span>
                <h2 id="missed-alert-title" className={styles.headline}>
                  A new lead came in and your phone stayed quiet
                </h2>
              </div>
            </div>
            <div className={styles.leadRow}>
              <span className={styles.avatar} aria-hidden="true">
                {initials(name)}
              </span>
              <span className={styles.leadWords}>
                <span className={styles.leadName}>{name}</span>
                {lead.detail ? (
                  <span className={styles.leadDetail}>{lead.detail}</span>
                ) : null}
              </span>
            </div>
            <p className={styles.body}>
              Turn on alerts so you never miss a hot lead.
            </p>
            <button
              type="button"
              className={styles.primary}
              onClick={() => void start()}
            >
              Turn on alerts
            </button>
            <button
              type="button"
              className={styles.textButton}
              onClick={openIt}
            >
              Open {firstName(name)}&rsquo;s lead
            </button>
          </div>
        ) : null}

        {stage.at === "step" ? (
          <div className={styles.step} key={`step-${stage.steps[stage.index]}`}>
            {(() => {
              const step = stage.steps[stage.index] ?? "notifications";
              const words = STEP_WORDS[step];
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
                    className={styles.stepGlyph}
                    data-step={step}
                    aria-hidden="true"
                  />
                  <h2 id="missed-alert-title" className={styles.stepTitle}>
                    {words.title}
                  </h2>
                  <p className={styles.stepWhy}>{words.why}</p>
                  {step !== "battery" ? (
                    <p className={styles.hint}>Android will ask you next.</p>
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
            {stage.facts?.notifications ? (
              <>
                <DrawnCheck />
                <h2 id="missed-alert-title" className={styles.doneTitle}>
                  All set
                </h2>
                <p className={styles.doneWhy}>
                  New leads will ring this phone.
                </p>
              </>
            ) : (
              <>
                <h2 id="missed-alert-title" className={styles.doneTitle}>
                  Alerts are still off
                </h2>
                <p className={styles.doneWhy}>
                  Turn on notifications for Sales X-Ray in Android&rsquo;s
                  settings so new leads ring this phone.
                </p>
              </>
            )}
            <ul className={styles.ticks}>
              {ALL_STEPS.map((step) => {
                const on = stage.facts
                  ? {
                      notifications: stage.facts.notifications,
                      phone: stage.facts.callAccess,
                      audio: stage.facts.audio,
                      battery: stage.facts.battery,
                    }[step]
                  : false;
                return (
                  <li
                    key={step}
                    className={styles.tick}
                    data-on={on ? "yes" : "no"}
                  >
                    <span className={styles.tickMark} aria-hidden="true" />
                    {STEP_WORDS[step].title}
                    <span className={styles.srOnly}>
                      {on ? ": on" : ": off"}
                    </span>
                  </li>
                );
              })}
            </ul>
            {stage.facts?.notifications ? null : (
              <button
                type="button"
                className={styles.secondary}
                onClick={() => void setupOpen("notifications")}
              >
                Open settings
              </button>
            )}
            <button type="button" className={styles.primary} onClick={openIt}>
              Open {firstName(name)}&rsquo;s lead
            </button>
          </div>
        ) : null}
      </section>
    </dialog>
  );
}

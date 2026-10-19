"use client";

/**
 * First run in the Sales Xray phone app (owner's phone test, 19 Oct): once the
 * Terms are accepted and before the app, one screen per permission, each saying
 * why, then Android's own question. Calls, notifications, recordings, then the
 * optional call recorder. "Not now" moves on; nothing is asked twice in a row.
 * Afterwards the Phone setup bar leaves Leads (the checklist stays in More and
 * on Team). Nothing shows in a browser, in an older app, or to someone who
 * signed in on this phone before.
 */

import {
  Bell,
  CheckCircle2,
  Circle,
  FileAudio,
  Mic,
  Phone,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { readConsent } from "../consent-renewal-client";
import { Button } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import {
  askCallAccess,
  askNotifications,
  askRecordingAccess,
  buzz,
  callRecorderOpen,
  callRecorderStart,
  callRecorderStatus,
  inPhoneApp,
  recorderOpen,
  setupStatus,
  type CallRecorderStatus,
  type SetupStatus,
} from "./native-phone";
import { EXPLAINERS, recorderSteps } from "./phone-setup-words";
import styles from "./phone-onboarding.module.css";

export const ONBOARDED_KEY = "sx-phone-onboarded";
const CHANGED = "sx-phone-onboarded";

export type OnboardingStep =
  | "calls"
  | "notifications"
  | "recordings"
  | "recorder";

type Screen = {
  icon: LucideIcon;
  title: string;
  lines: string[];
  allow: string;
  optional?: boolean;
  /** Recorder steps to read before opening the phone's settings. */
  steps?: string[];
};

/** True once this phone went through the first run (or skipped it). */
export function phoneOnboarded(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDED_KEY) !== null;
  } catch {
    return true;
  }
}

function markOnboarded() {
  try {
    window.localStorage.setItem(ONBOARDED_KEY, new Date().toISOString());
  } catch {
    // Private storage off: the first run may show again; nothing breaks.
  }
  window.dispatchEvent(new Event(CHANGED));
}

/** Re-renders when the first run finishes, so the Phone setup bar can leave. */
export function usePhoneOnboarded(): boolean {
  const [done, setDone] = useState(true);
  useEffect(() => {
    const read = () => setDone(phoneOnboarded());
    read();
    window.addEventListener(CHANGED, read);
    return () => window.removeEventListener(CHANGED, read);
  }, []);
  return done;
}

/** The steps this phone still needs, in order; the recorder only where it helps. */
export function onboardingSteps(
  status: SetupStatus,
  recorder: CallRecorderStatus | null,
): OnboardingStep[] {
  const steps: OnboardingStep[] = [];
  if (!status.checks.calls) steps.push("calls");
  if (!status.checks.notifications) steps.push("notifications");
  if (!status.checks.recordings) steps.push("recordings");
  const dialerOff =
    status.recorder?.kind === "folder" && status.recorder.recording !== "on";
  if (
    (recorder?.available && !recorder.enabled) ||
    (!recorder?.available && dialerOff)
  )
    steps.push("recorder");
  return steps;
}

function screenFor(
  step: OnboardingStep,
  status: SetupStatus,
  recorder: CallRecorderStatus | null,
): Screen {
  if (step === "recorder") {
    if (recorder?.available)
      return {
        icon: Mic,
        title: "Record your calls (optional)",
        lines: [
          "Sales Xray can record your work calls itself, on phones whose dialer doesn't.",
          "Tell the other person the call is recorded. Recordings stay on this phone until you choose one to analyse.",
          "Android asks you to switch it on in Accessibility. If it says the setting is restricted, open App info, tap ⋮ and Allow restricted settings, then try again.",
        ],
        allow: "Open Accessibility",
        optional: true,
      };
    return {
      icon: Mic,
      title: "Turn on call recording (optional)",
      lines: [
        `${status.recorder?.dialerLabel ?? "Your Phone app"} can save every call. Sales Xray finds those recordings so a call can get its Report.`,
      ],
      steps: recorderSteps(status.family),
      allow: "Open Phone settings",
      optional: true,
    };
  }
  const words = EXPLAINERS[step];
  const icon =
    step === "calls" ? Phone : step === "notifications" ? Bell : FileAudio;
  return {
    icon,
    title: words?.title ?? step,
    lines: words
      ? [words.why, `Reads: ${words.reads}`, `Leaves the phone: ${words.sends}`]
      : [],
    allow: words?.allow ?? "Allow",
  };
}

async function allow(
  step: OnboardingStep,
  recorder: CallRecorderStatus | null,
) {
  if (step === "calls") await askCallAccess();
  else if (step === "notifications") await askNotifications();
  else if (step === "recordings") await askRecordingAccess();
  else if (recorder?.available) {
    await callRecorderStart();
    await callRecorderOpen("accessibility");
  } else await recorderOpen("settings");
}

export function PhoneOnboarding() {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true;
  const [plan, setPlan] = useState<{
    steps: OnboardingStep[];
    status: SetupStatus;
    recorder: CallRecorderStatus | null;
  } | null>(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SetupStatus | null>(null);

  // Waits for the Terms card: it covers the page while consent isn't current.
  useEffect(() => {
    if (!signedIn || !inPhoneApp() || phoneOnboarded()) return;
    let stopped = false;
    const start = async () => {
      if (stopped || document.documentElement.hasAttribute("data-sx-consent"))
        return;
      try {
        if ((await readConsent()).status !== "current") return;
      } catch {
        return;
      }
      const status = await setupStatus();
      if (stopped || !status) return; // an app too old to say
      const recorder = await callRecorderStatus();
      const steps = onboardingSteps(status, recorder);
      if (!steps.length) {
        markOnboarded();
        return;
      }
      setPlan({ steps, status, recorder });
    };
    void start();
    const watch = new MutationObserver(() => void start());
    watch.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-sx-consent"],
    });
    return () => {
      stopped = true;
      watch.disconnect();
    };
  }, [signedIn]);

  const next = useCallback(async () => {
    if (!plan) return;
    if (index + 1 < plan.steps.length) {
      setIndex(index + 1);
      return;
    }
    setResult((await setupStatus()) ?? plan.status);
    setIndex(plan.steps.length);
  }, [plan, index]);

  if (!plan) return null;
  const finish = () => {
    buzz("done");
    markOnboarded();
    setPlan(null);
  };

  if (index >= plan.steps.length) {
    const checks = (result ?? plan.status).checks;
    const rows: [string, boolean][] = [
      ["Calls", !!checks.calls],
      ["Notifications", !!checks.notifications],
      ["Call recordings", !!checks.recordings],
    ];
    return (
      <div
        className={styles.page}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sx-onboard-done"
      >
        <div className={styles.body}>
          <span className={styles.icon} data-done="">
            <CheckCircle2 size={28} aria-hidden="true" />
          </span>
          <h1 id="sx-onboard-done" className={styles.title}>
            Your phone is ready
          </h1>
          <ul className={styles.summary}>
            {rows.map(([label, on]) => (
              <li key={label} data-on={on ? "" : undefined}>
                {on ? (
                  <CheckCircle2 size={18} aria-hidden="true" />
                ) : (
                  <Circle size={18} aria-hidden="true" />
                )}
                {label}
                <span>{on ? "On" : "Off"}</span>
              </li>
            ))}
          </ul>
          <p className={styles.line}>
            Anything left off can be turned on later in More, Phone setup.
          </p>
        </div>
        <div className={styles.actions}>
          <Button variant="primary" onClick={finish}>
            Open Sales Xray
          </Button>
        </div>
      </div>
    );
  }

  const step = plan.steps[index];
  const screen = screenFor(step, plan.status, plan.recorder);
  const Icon = screen.icon;
  return (
    <div
      className={styles.page}
      role="dialog"
      aria-modal="true"
      aria-labelledby="sx-onboard-title"
    >
      <div className={styles.body}>
        <p className={styles.progress}>
          Step {index + 1} of {plan.steps.length}
        </p>
        <span className={styles.icon}>
          <Icon size={28} aria-hidden="true" />
        </span>
        <h1 id="sx-onboard-title" className={styles.title}>
          {screen.title}
        </h1>
        {screen.lines.map((line) => (
          <p key={line} className={styles.line}>
            {line}
          </p>
        ))}
        {screen.steps ? (
          <ol className={styles.steps}>
            {screen.steps.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
        ) : null}
      </div>
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={busy}
          aria-busy={busy || undefined}
          onClick={async () => {
            setBusy(true);
            try {
              await allow(step, plan.recorder);
            } finally {
              setBusy(false);
              void next();
            }
          }}
        >
          {screen.allow}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => void next()}>
          {screen.optional ? "Skip" : "Not now"}
        </Button>
      </div>
    </div>
  );
}

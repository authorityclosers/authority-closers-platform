"use client";

/**
 * "Set up this phone": one guided flow (owner, 24 Oct 2026: "all these
 * settings are terrible for UX we need to make it simpler least steps
 * workflows"). It replaces the first-run screens and the checklist's page per
 * line: one screen for each thing this phone still needs, one sentence on
 * why, one button, Android's own question, and on to the next by itself.
 * Anything already allowed is skipped. Later moves on; closing keeps the rest
 * for next time, which starts at the first thing still to do. Work-call
 * logging is offered, never turned on without a tap.
 *
 * What Sales X-Ray reads and what leaves the phone stay worded as Google Play
 * needs them (phone-setup-words.ts, 3d8e6aed), small under the reason.
 */

import {
  Bell,
  BatteryCharging,
  FileAudio,
  History,
  Mic,
  Phone,
  Power,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { notify } from "../notice-center";
import { useBackClose } from "../ui/back-close";
import { Button } from "../ui/kit";
import {
  askCallAccess,
  askNotifications,
  askRecordingAccess,
  buzz,
  callLogSetup,
  callLogStatus,
  callRecorderOpen,
  callRecorderStart,
  callRecorderStatus,
  onPhoneSignal,
  pickRecordingsFolder,
  recorderOpen,
  setupMark,
  setupOpen,
  setupStatus,
  type CallLogStatus,
  type CallRecorderStatus,
  type SetupStatus,
} from "./native-phone";
import {
  ALL_FILES_EXPLAINER,
  CHECK_TODO,
  FOLDER_EXPLAINER,
  explainerFor,
  recorderGuide,
} from "./phone-setup-words";
import styles from "./phone-onboarding.module.css";
import {
  allFiles,
  blocked,
  done,
  flowSteps,
  folderPick,
  type FlowStep,
} from "./phone-setup-steps";

export { blocked, flowSteps } from "./phone-setup-steps";
export type { FlowStep } from "./phone-setup-steps";

export type FlowScreen = {
  icon: LucideIcon;
  title: string;
  /** One sentence on why. */
  why: string;
  /** Play's wording, when the step reads or sends anything. */
  reads?: string;
  sends?: string;
  action: string;
  /** The button opens one of Android's settings screens; the flow waits for the way back. */
  away: boolean;
  /** Steps to follow in that screen (the call recorder). */
  steps?: string[];
};

const nothing = (words: string | undefined) =>
  !words || words.startsWith("Nothing");

/** A step's screen, for this phone and this build of the app. */
export function flowScreen(
  step: FlowStep,
  status: SetupStatus,
  recorder: CallRecorderStatus | null,
): FlowScreen {
  if (step === "battery")
    return {
      icon: BatteryCharging,
      title: "Battery unrestricted",
      why:
        status.store === "play"
          ? "So your lead alerts arrive on time. Sales X-Ray uses very little battery."
          : "So your calls are logged and alerts arrive on time. Sales X-Ray uses very little battery.",
      action: "Open battery settings",
      away: true,
    };
  if (step === "autostart")
    return {
      icon: Power,
      title: "Autostart",
      why: "So alerts still come after your phone restarts: switch Sales X-Ray on, then come back.",
      action: "Open Autostart",
      away: true,
    };
  if (step === "callLog")
    return {
      icon: History,
      title: "Log work calls",
      why: `${CHECK_TODO.callLog} Other numbers never leave your phone.`,
      action: "Turn on",
      away: false,
    };
  if (step === "recorder") {
    if (recorder?.available)
      return {
        icon: Mic,
        title: "Record your calls",
        why: "Sales X-Ray can record work calls on phones whose dialer doesn't. Tell the other person the call is recorded.",
        action: "Open Accessibility",
        away: true,
      };
    const guide = recorderGuide(status.recorder, status.family);
    // Google's Phone app keeps its recordings to itself: another Phone app, or none.
    if (guide.closed)
      return {
        icon: Mic,
        title: "Call recording",
        why: guide.lead ?? "",
        steps: guide.steps,
        action: status.recorder?.switchTo ? "Choose the Phone app" : "Got it",
        away: Boolean(status.recorder?.switchTo),
      };
    return {
      icon: Mic,
      title: "Turn on call recording",
      why:
        guide.lead ??
        `${status.recorder?.dialerLabel ?? "Your Phone app"} can save every call, so a call can get its Report.`,
      steps: guide.steps,
      action: "Open call recording settings",
      away: true,
    };
  }
  const words =
    step === "recordings" && allFiles(status)
      ? ALL_FILES_EXPLAINER
      : step === "recordings" && folderPick(status)
        ? FOLDER_EXPLAINER
        : explainerFor(step, status.store);
  // Android won't show its question again: the button opens the settings.
  const stuck = blocked(step, status);
  return {
    icon:
      step === "calls" ? Phone : step === "notifications" ? Bell : FileAudio,
    title: words?.title ?? "Phone setup",
    why: stuck
      ? "Android won't ask again here. Allow it in Settings, then come back."
      : (words?.why ?? ""),
    reads: nothing(words?.reads) ? undefined : words?.reads,
    sends: nothing(words?.sends) ? undefined : words?.sends,
    action: stuck ? "Open settings" : (words?.allow ?? "Allow"),
    away: stuck || (step === "recordings" && allFiles(status)),
  };
}

async function act(
  step: FlowStep,
  status: SetupStatus,
  recorder: CallRecorderStatus | null,
  sim: string,
): Promise<unknown> {
  if (blocked(step, status))
    return setupOpen(
      step === "notifications" ? "notifications" : "appSettings",
    );
  switch (step) {
    case "calls":
      return askCallAccess();
    case "notifications":
      return askNotifications();
    case "recordings":
      if (allFiles(status)) return setupOpen("allFiles");
      if (folderPick(status)) return pickRecordingsFolder();
      return askRecordingAccess();
    case "battery":
      return setupOpen("battery");
    case "autostart":
      return setupOpen("autostart");
    case "callLog":
      return callLogSetup(true, sim);
    case "recorder":
      if (recorder?.available) {
        await callRecorderStart();
        return callRecorderOpen("accessibility");
      }
      if (recorderGuide(status.recorder, status.family).closed)
        return status.recorder?.switchTo
          ? recorderOpen("defaultDialer")
          : false;
      return setupOpen("recorder");
  }
}

/**
 * The flow over the page. `only` sets up that one thing (Settings' Fix);
 * otherwise everything still to do, in order. `onClose` gets the phone's
 * state when it ends.
 */
export function PhoneSetupFlow({
  only,
  onClose,
}: {
  only?: FlowStep;
  onClose: (status: SetupStatus | null) => void;
}) {
  const [plan, setPlan] = useState<{
    steps: FlowStep[];
    status: SetupStatus;
    recorder: CallRecorderStatus | null;
  } | null>(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [away, setAway] = useState<FlowStep | null>(null);
  const [log, setLog] = useState<CallLogStatus | null>(null);
  const [sim, setSim] = useState("");
  const closed = useRef(false);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  const end = useCallback((status: SetupStatus | null, steps: FlowStep[]) => {
    if (closed.current) return;
    closed.current = true;
    const left = status ? flowSteps(status, null).length : steps.length;
    if (status && steps.length) {
      buzz("done");
      notify({
        id: "phone-setup",
        tone: left ? "info" : "success",
        title: left
          ? `${left} more ${left === 1 ? "thing" : "things"} to set up`
          : "Your phone is set up",
        message: left
          ? "Finish any time from Settings, Phone."
          : "Calls, alerts and recordings are ready.",
      });
    }
    onCloseRef.current(status);
  }, []);

  // What this phone still needs, read once when the flow opens.
  useEffect(() => {
    let alive = true;
    void (async () => {
      const status = await setupStatus();
      if (!alive) return;
      if (!status) {
        end(null, []);
        return;
      }
      const recorder = await callRecorderStatus();
      if (!alive) return;
      // Settings' Fix: that one line, whatever else is left.
      const steps = only
        ? done(status, only)
          ? []
          : [only]
        : flowSteps(status, recorder);
      if (!steps.length) {
        end(status, []);
        return;
      }
      setPlan({ steps, status, recorder });
    })();
    return () => {
      alive = false;
    };
  }, [only, end]);

  const step = plan ? plan.steps[index] : undefined;

  // Logging work calls on a phone with two SIMs: which one is for work.
  useEffect(() => {
    if (step !== "callLog") return;
    let alive = true;
    void callLogStatus().then((next) => {
      if (!alive || !next) return;
      setLog(next);
      setSim((current) => current || next.sim || next.sims[0]?.id || "");
    });
    return () => {
      alive = false;
    };
  }, [step]);

  const advance = useCallback(async () => {
    if (!plan) return;
    const status = (await setupStatus()) ?? plan.status;
    if (index + 1 >= plan.steps.length) {
      end(status, plan.steps);
      return;
    }
    setPlan({ ...plan, status });
    setIndex(index + 1);
  }, [plan, index, end]);

  // Back from one of Android's settings screens: on to the next step.
  useEffect(() => {
    if (!away) return;
    return onPhoneSignal((event) => {
      if (event !== "resume") return;
      setAway(null);
      void (async () => {
        // Android can't tell an app whether Autostart or the dialer's
        // recording is on: coming back from that screen counts.
        if (away === "autostart" || away === "recorder")
          await setupMark(away, true);
        await advance();
      })();
    });
  }, [away, advance]);

  // A modal dialog, so it sits above Phone setup's own sheet.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = frame.current;
    if (node && !node.open) node.showModal?.();
  }, [plan]);

  const close = useCallback(() => {
    void setupStatus().then((status) =>
      end(status ?? plan?.status ?? null, plan?.steps ?? []),
    );
  }, [end, plan]);
  useBackClose(plan !== null, close);

  if (!plan || !step) return null;
  const screen = flowScreen(step, plan.status, plan.recorder);
  const Icon = screen.icon;
  const go = async () => {
    setBusy(true);
    let opened: unknown = null;
    try {
      opened = await act(step, plan.status, plan.recorder, sim);
    } catch {
      // Android said no, or the phone didn't answer: the step stays to do.
    }
    setBusy(false);
    // A settings screen that didn't open has no way back to wait for.
    if (screen.away && opened !== false) setAway(step);
    else await advance();
  };

  return (
    <dialog
      ref={frame}
      className={styles.page}
      aria-labelledby="sx-setup-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className={styles.top}>
        {plan.steps.length > 1 ? (
          <ol
            className={styles.dots}
            aria-label={`Step ${index + 1} of ${plan.steps.length}`}
          >
            {plan.steps.map((item, at) => (
              <li key={item} data-on={at <= index ? "" : undefined} />
            ))}
          </ol>
        ) : (
          <span />
        )}
        <button
          type="button"
          className={styles.close}
          aria-label="Close phone setup"
          onClick={close}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className={styles.body}>
        <span className={styles.icon}>
          <Icon size={28} aria-hidden="true" />
        </span>
        <h1 id="sx-setup-title" className={styles.title}>
          {screen.title}
        </h1>
        <p className={styles.line}>{screen.why}</p>
        {screen.steps ? (
          <ol className={styles.steps}>
            {screen.steps.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
        ) : null}
        {step === "callLog" && log && log.sims.length > 1 ? (
          <div className={styles.sims} role="group" aria-label="Work SIM">
            {log.sims.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={sim === item.id}
                onClick={() => setSim(item.id)}
              >
                {item.label || "SIM"}
              </button>
            ))}
          </div>
        ) : null}
        {screen.reads || screen.sends ? (
          <dl className={styles.fine}>
            {screen.reads ? (
              <div>
                <dt>Reads</dt>
                <dd>{screen.reads}</dd>
              </div>
            ) : null}
            {screen.sends ? (
              <div>
                <dt>Leaves your phone</dt>
                <dd>{screen.sends}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </div>
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={busy || away !== null}
          aria-busy={busy || undefined}
          onClick={() => void go()}
        >
          {away ? "Waiting for you to come back…" : screen.action}
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => {
            setAway(null);
            void advance();
          }}
        >
          Later
        </Button>
      </div>
    </dialog>
  );
}

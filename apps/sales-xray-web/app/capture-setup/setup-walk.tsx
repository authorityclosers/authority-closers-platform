"use client";

/**
 * Phone setup, one ask per screen (owner, 20 Nov 2026: style C "See what to
 * tap", "implement this and make it live on the next version"). Each screen
 * asks one thing: a picture of the exact phone screen that comes next with the
 * button to press ringed, a headline, one sentence, one green button pinned in
 * thumb reach and a quiet Not now. Granted screens are skipped, coming back
 * from Android's question lands on the next screen, and the screen is kept on
 * this phone so closing the app resumes.
 *
 * The walk only shows and moves; what each button asks of Android, and what
 * Not now remembers, is the gate's (permissions-gate.tsx), so the rules of
 * what holds the app stay in one place (permissions-rules.ts).
 *
 * The consent screen shows the sealed words exactly as the server has them,
 * in full, with equal Turn on and Not now and nothing pre-ticked.
 */

import {
  BarChart3,
  BatteryCharging,
  Bell,
  ChevronLeft,
  FolderOpen,
  Phone,
  PhoneCall,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { SetupStatus } from "../leads/native-phone";
import { Button } from "../ui/kit";
import walk from "./setup-walk.module.css";
import {
  CALL_STEPS,
  WALK_STEP_KEY,
  WALK_WELCOMED_KEY,
  askSteps,
  isAsk,
  nextStep,
  readKey,
  resumeAt,
  writeKey,
  type AskStep,
  type WalkStep,
} from "./setup-walk-steps";
import {
  ALL_SET,
  ALMOST_SET,
  WELCOME,
  batteryLines,
  folderPath,
  stepWords,
  welcomeLine,
  type StepWords,
} from "./setup-walk-words";
import {
  DoneArt,
  ShieldArt,
  WalkArt,
  type ArtProps,
} from "./walk-art/walk-art";

/** The page's layout: top bar, the step, and its buttons pinned at the foot. */
export function WalkFrame({
  titleId,
  progress,
  onBack,
  onClose,
  art,
  title,
  children,
  actions,
}: {
  titleId: string;
  /** "Step N of M" (index from 0); none on the welcome and the end. */
  progress?: { index: number; total: number } | null;
  onBack?: () => void;
  onClose?: () => void;
  art?: ReactNode;
  title: string;
  children?: ReactNode;
  actions: ReactNode;
}) {
  return (
    <>
      <div className={walk.top}>
        {onBack ? (
          <button
            type="button"
            className={walk.iconButton}
            aria-label="Back"
            onClick={onBack}
          >
            <ChevronLeft size={24} aria-hidden="true" />
          </button>
        ) : (
          <span className={walk.spacer} />
        )}
        {progress && progress.total > 1 ? (
          <div className={walk.progress}>
            <ol
              className={walk.dots}
              aria-label={`Step ${progress.index + 1} of ${progress.total}`}
            >
              {Array.from({ length: progress.total }, (_, at) => (
                <li key={at} data-on={at <= progress.index ? "" : undefined} />
              ))}
            </ol>
            <span className={walk.count} aria-hidden="true">
              Step {progress.index + 1} of {progress.total}
            </span>
          </div>
        ) : (
          <span />
        )}
        {onClose ? (
          <button
            type="button"
            className={walk.iconButton}
            aria-label="Close phone setup"
            onClick={onClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        ) : (
          <span className={walk.spacer} />
        )}
      </div>
      <div className={walk.body}>
        <h1 id={titleId} className={walk.title}>
          {title}
        </h1>
        {children}
        {art ? <div className={walk.art}>{art}</div> : null}
      </div>
      <div className={walk.actions}>{actions}</div>
    </>
  );
}

const WELCOME_ROWS: Readonly<
  Record<AskStep, { icon: LucideIcon; label: string }>
> = {
  alerts: { icon: Bell, label: "Alerts" },
  calls: { icon: Phone, label: "Calls" },
  recordings: { icon: FolderOpen, label: "Recordings" },
  battery: { icon: BatteryCharging, label: "Battery" },
  analyse: { icon: BarChart3, label: "Analyse calls" },
  test_call: { icon: PhoneCall, label: "Test call" },
};

/** The picture for a step on this phone. */
export function artFor(
  step: AskStep,
  status: SetupStatus,
  {
    settings,
    questions,
    phase,
  }: {
    settings: boolean;
    questions: readonly string[];
    phase: "battery" | "autostart";
  },
): ArtProps | null {
  switch (step) {
    case "alerts":
      return { kind: settings ? "alerts-settings" : "alerts" };
    case "calls":
      return settings || !questions.length
        ? { kind: "calls-settings" }
        : { kind: "calls", questions };
    case "recordings":
      return status.recorder?.kind === "private"
        ? { kind: "recordings-private" }
        : { kind: "recordings", path: folderPath(status) };
    case "battery": {
      const [battery, autostart] = batteryLines(status);
      if (phase === "autostart" && autostart)
        return { kind: "autostart", page: autostart.page };
      return {
        kind: "battery",
        page: battery?.page,
        choose: battery?.choose,
        others:
          status.family === "xiaomi"
            ? ["Battery saver (recommended)", "Restrict background apps"]
            : ["Optimised", "Restricted"],
        autostart: autostart?.page,
      };
    }
    case "test_call":
      return { kind: "test-call" };
    case "analyse":
      return null;
  }
}

export type SetupWalkProps = Readonly<{
  /** Start here instead of where the walk left off (the review fixture). */
  start?: WalkStep;
  /** The screens of this walk (walkSteps), fixed while it runs. */
  steps: readonly WalkStep[];
  /** Whether a screen still has something to ask, read live. */
  stillOpen: (step: AskStep) => boolean;
  status: SetupStatus;
  /** Android won't ask again for this screen's question: Open settings. */
  settingsFor: (step: AskStep) => boolean;
  /** Android's questions on the calls screen, in order. */
  questions: readonly string[];
  /** The battery screen: battery first, then Autostart. */
  batteryPhase: "battery" | "autostart";
  /** The test call: not placed yet, waiting for its recording, or none found. */
  test: "ready" | "waiting" | "missing";
  /** The sealed consent words and the upload terms' details, from the server. */
  consent: { words: string; terms?: string } | null;
  /** This phone makes no calls (the all-set words). */
  noCalls?: boolean;
  busy: boolean;
  /** A line under the sentence (a picker cancelled, a screen that didn't open). */
  note?: string | null;
  /** The quiet button's spoken name: "Not now: Call log". */
  laterLabel: (step: AskStep) => string;
  onAsk: (step: AskStep) => void;
  onLater: (step: AskStep) => void;
  onNoCalls: () => void;
  onShown: (step: WalkStep, index: number, total: number) => void;
  /** The walk ended: Go to Home, or nothing left to ask. */
  onEnd: () => void;
}>;

export function SetupWalk(props: SetupWalkProps) {
  const { steps, stillOpen, status } = props;
  const titleId = useId();
  const [shown, setCurrent] = useState<WalkStep | null>(
    () => props.start ?? resumeAt(steps, readKey(WALK_STEP_KEY), stillOpen),
  );
  // Granted, put off, or answered in Android's dialog: on to the next screen.
  const current =
    shown && isAsk(shown) && !stillOpen(shown)
      ? nextStep(steps, shown, stillOpen)
      : shown;
  const ended = useRef(false);
  // Something was put off on the way: the end says so.
  const [putOff, setPutOff] = useState(false);
  const later = (step: AskStep) => {
    if (step !== "test_call") setPutOff(true);
    props.onLater(step);
  };
  const onEnd = useRef(props.onEnd);
  const onShown = useRef(props.onShown);
  useEffect(() => {
    onEnd.current = props.onEnd;
    onShown.current = props.onShown;
  });

  const asks = askSteps(steps);
  const index = current && isAsk(current) ? asks.indexOf(current) : -1;

  // Kept on this phone so closing the app resumes; cleared at the end.
  useEffect(() => {
    if (current && current !== "all_set") writeKey(WALK_STEP_KEY, current);
    else writeKey(WALK_STEP_KEY, null);
    if (current === null && !ended.current) {
      ended.current = true;
      onEnd.current();
    }
  }, [current]);

  useEffect(() => {
    if (current) onShown.current(current, Math.max(0, index), asks.length);
  }, [current, index, asks.length]);

  if (!current) return null;

  const back = (() => {
    const at = steps.indexOf(current);
    for (let i = at - 1; i >= 0; i--) {
      const step = steps[i];
      if (step && (!isAsk(step) || stillOpen(step))) return step;
    }
    return null;
  })();
  const goBack = back ? () => setCurrent(back) : undefined;

  if (current === "welcome") {
    return (
      <WalkFrame
        titleId={titleId}
        onBack={undefined}
        title={WELCOME.title}
        actions={
          <>
            <Button
              variant="primary"
              className={walk.primary}
              onClick={() => {
                writeKey(WALK_WELCOMED_KEY, "1");
                setCurrent(nextStep(steps, "welcome", stillOpen));
              }}
            >
              {WELCOME.action}
            </Button>
            <Button
              variant="ghost"
              className={walk.quiet}
              onClick={() => {
                writeKey(WALK_WELCOMED_KEY, "1");
                props.onNoCalls();
                const left = steps.filter(
                  (step) => !isAsk(step) || !CALL_STEPS.has(step),
                );
                setCurrent(
                  nextStep(
                    left,
                    "welcome",
                    (step) => !CALL_STEPS.has(step) && stillOpen(step),
                  ),
                );
              }}
            >
              {WELCOME.later}
            </Button>
          </>
        }
      >
        <p className={walk.line}>{welcomeLine(asks.length)}</p>
        <ul className={walk.plan}>
          {asks.map((step) => {
            const { icon: Icon, label } = WELCOME_ROWS[step];
            return (
              <li key={step}>
                <Icon size={20} aria-hidden="true" />
                {label}
              </li>
            );
          })}
        </ul>
      </WalkFrame>
    );
  }

  if (current === "all_set") {
    const almost =
      putOff || asks.some((step) => step !== "test_call" && stillOpen(step));
    const words = almost
      ? ALMOST_SET
      : props.noCalls
        ? { ...ALL_SET, line: "Sales X-Ray is ready on this phone." }
        : ALL_SET;
    return (
      <WalkFrame
        titleId={titleId}
        title={words.title}
        art={almost ? null : <DoneArt />}
        actions={
          <Button
            variant="primary"
            className={walk.primary}
            onClick={() => setCurrent(null)}
          >
            {words.action}
          </Button>
        }
      >
        <p className={walk.line}>{words.line}</p>
      </WalkFrame>
    );
  }

  const step = current;
  const settings = props.settingsFor(step);
  const words: StepWords = stepWords(step, status, {
    settings,
    dialogs: props.questions.length,
    phase: props.batteryPhase,
    test: props.test,
  });
  const picture = artFor(step, status, {
    settings,
    questions: props.questions,
    phase: props.batteryPhase,
  });
  const progress = { index, total: asks.length };

  if (step === "analyse")
    return (
      <WalkFrame
        titleId={titleId}
        progress={progress}
        onBack={goBack}
        title={words.title}
        actions={
          <div className={walk.pair}>
            <Button
              variant="primary"
              className={walk.primary}
              disabled={props.busy || !props.consent}
              aria-busy={props.busy || undefined}
              onClick={() => props.onAsk(step)}
            >
              {words.action}
            </Button>
            <Button
              variant="secondary"
              className={walk.secondary}
              disabled={props.busy}
              aria-label={props.laterLabel(step)}
              onClick={() => later(step)}
            >
              {words.later}
            </Button>
          </div>
        }
      >
        <ShieldArt />
        {props.consent ? (
          <div className={walk.consent} data-sx-consent-words="">
            {/* The sealed consent words, exactly as the server has them. */}
            <p>{props.consent.words}</p>
            {props.consent.terms ? (
              <details className={walk.terms}>
                <summary>Read the full terms</summary>
                <p>{props.consent.terms}</p>
              </details>
            ) : null}
          </div>
        ) : null}
      </WalkFrame>
    );

  return (
    <WalkFrame
      titleId={titleId}
      progress={progress}
      onBack={goBack}
      title={words.title}
      art={picture ? <WalkArt {...picture} /> : null}
      actions={
        <>
          <Button
            variant="primary"
            className={walk.primary}
            disabled={props.busy}
            aria-busy={props.busy || undefined}
            onClick={() => props.onAsk(step)}
          >
            {words.action}
          </Button>
          <Button
            variant="ghost"
            className={walk.quiet}
            disabled={props.busy}
            aria-label={props.laterLabel(step)}
            onClick={() => later(step)}
          >
            {words.later}
          </Button>
        </>
      }
    >
      {words.line ? <p className={walk.line}>{words.line}</p> : null}
      {step === "battery" ? (
        <ol className={walk.numbered}>
          {batteryLines(status).map((line, at) => (
            <li
              key={line.page}
              data-on={
                (props.batteryPhase === "autostart" ? 1 : 0) === at
                  ? ""
                  : undefined
              }
            >
              {line.page} → {line.choose}
            </li>
          ))}
        </ol>
      ) : null}
      {words.note ? <p className={walk.note}>{words.note}</p> : null}
      {props.note ? (
        <p className={walk.alert} role="status">
          {props.note}
        </p>
      ) : null}
    </WalkFrame>
  );
}

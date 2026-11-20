/**
 * Phone setup, one ask per screen (owner, 20 Nov 2026, style C "See what to
 * tap"): which screens this phone shows, in which order, and where a walk
 * picks up again. Pure, so the gate decides without loading the screens.
 *
 * The order (STUDY.md §5): welcome, alerts, calls, recordings folder, battery
 * and Autostart, "Analyse my calls automatically", an optional test call, then
 * all set. What is granted is left out, and so is what this phone or build
 * can't do; the dots count only what is left. Someone who doesn't make calls
 * on this phone sees no calls, recordings, battery or test call.
 */

import type { SetupStatus } from "../leads/native-phone";
import type { FlowStep } from "../leads/phone-setup-steps";
import type { FlowStep as TelemetryStep } from "../telemetry";
import {
  putOffKey,
  toAnswer,
  type PermissionItem,
  type PermissionKey,
} from "./permissions-rules";

export type WalkStep =
  | "welcome"
  | "alerts"
  | "calls"
  | "recordings"
  | "battery"
  | "analyse"
  | "test_call"
  | "all_set";

export type AskStep = Exclude<WalkStep, "welcome" | "all_set">;

export const ASK_STEPS: readonly AskStep[] = [
  "alerts",
  "calls",
  "recordings",
  "battery",
  "analyse",
  "test_call",
];

export const isAsk = (step: WalkStep): step is AskStep =>
  step !== "welcome" && step !== "all_set";

/** The gate's rows each screen answers. The test call answers none. */
export const STEP_KEYS: Readonly<Record<AskStep, readonly PermissionKey[]>> = {
  alerts: ["notifications"],
  calls: ["phone", "callLog", "contacts"],
  recordings: ["recordings"],
  battery: ["battery"],
  analyse: ["autoAnalysis"],
  test_call: [],
};

/** The screens someone who doesn't make calls on this phone never sees. */
export const CALL_STEPS: ReadonlySet<AskStep> = new Set<AskStep>([
  "calls",
  "recordings",
  "battery",
  "test_call",
]);
const CALL_KEYS: ReadonlySet<PermissionKey> = new Set(
  [...CALL_STEPS].flatMap((step) => STEP_KEYS[step]),
);

/** The walk's screen as the friction report names it (sx.flow step). */
export const WALK_TELEMETRY: Readonly<Record<WalkStep, TelemetryStep>> = {
  welcome: "welcome",
  alerts: "notifications",
  calls: "calls",
  recordings: "recordings",
  battery: "battery",
  analyse: "analyse",
  test_call: "test_call",
  all_set: "all_set",
};

/** The Android ask a screen makes, as phone setup's prompt telemetry names it. */
export const WALK_PROMPT: Readonly<Partial<Record<AskStep, FlowStep>>> = {
  alerts: "notifications",
  calls: "calls",
  recordings: "recordings",
  battery: "battery",
};

/** The step that answers a row. */
export function stepOf(key: PermissionKey): AskStep {
  return ASK_STEPS.find((step) => STEP_KEYS[step].includes(key)) ?? "calls";
}

/**
 * The rows still to answer now: what the gate waits for and what wasn't put
 * off (toAnswer), less what was put off for this app open only (a needed row's
 * Not now: it asks again at the next open), and less the call rows when this
 * phone makes no calls.
 */
export function pendingKeys(
  items: readonly PermissionItem[],
  {
    putOff,
    skipped,
    makesCalls,
  }: {
    putOff: ReadonlySet<string>;
    skipped: ReadonlySet<string>;
    makesCalls: boolean;
  },
): Set<PermissionKey> {
  return new Set(
    toAnswer(items, putOff)
      .filter((item) => !skipped.has(putOffKey(item)))
      .filter((item) => makesCalls || !CALL_KEYS.has(item.key))
      .map((item) => item.key),
  );
}

export type WalkFacts = Readonly<{
  /** pendingKeys: the rows still to answer. */
  pending: ReadonlySet<PermissionKey>;
  status: SetupStatus;
  /** "I don't make calls on this phone" wasn't chosen. */
  makesCalls: boolean;
  /** The welcome was shown on this phone already, or a walk is under way. */
  welcomed: boolean;
  /** A recording was found on this phone already, or the test call was skipped. */
  tested: boolean;
  /** Google's Phone app keeps recordings private, and that was said once. */
  privateSeen: boolean;
}>;

/** Google's Phone app keeps its recordings to itself: nothing to pick. */
export const privateRecorder = (status: SetupStatus) =>
  status.recorder?.kind === "private";

/** Calls and recordings both reach Sales X-Ray: a test call can prove it. */
export function captureReady(status: SetupStatus): boolean {
  return (
    status.recorder?.kind === "folder" &&
    status.checks.calls === true &&
    (status.folderPicked || status.checks.recordings === true)
  );
}

/** Whether a screen still has something to ask on this phone. */
export function stepOpen(step: AskStep, facts: WalkFacts): boolean {
  const has = (key: PermissionKey) => facts.pending.has(key);
  switch (step) {
    case "alerts":
      return has("notifications");
    case "calls":
      return (
        facts.makesCalls && (has("phone") || has("callLog") || has("contacts"))
      );
    case "recordings":
      return (
        facts.makesCalls &&
        has("recordings") &&
        !(privateRecorder(facts.status) && facts.privateSeen)
      );
    case "battery":
      return facts.makesCalls && has("battery");
    case "analyse":
      return has("autoAnalysis");
    case "test_call":
      return (
        facts.makesCalls &&
        !facts.tested &&
        facts.status.recorder?.kind === "folder"
      );
  }
}

/**
 * The screens of a walk, in order. A walk opened at one screen (the Calls
 * line's Turn on, a Fix) is that screen alone. A whole walk has the welcome
 * the first time on this phone and the all-set screen when it asks two or
 * more things; the test call joins only a walk that asks something else.
 */
export function walkSteps(facts: WalkFacts, only?: AskStep): WalkStep[] {
  if (only) return stepOpen(only, facts) ? [only] : [];
  const asks = ASK_STEPS.filter((step) => stepOpen(step, facts));
  if (!asks.some((step) => step !== "test_call")) return [];
  const many = asks.length > 1;
  return [
    ...(facts.welcomed || !many ? [] : (["welcome"] as const)),
    ...asks,
    ...(many ? (["all_set"] as const) : []),
  ];
}

/** The ask screens of a walk: what "Step N of M" counts. */
export const askSteps = (steps: readonly WalkStep[]): AskStep[] =>
  steps.filter(isAsk);

/**
 * The screen after `current` that still has something to ask; the welcome
 * and the all-set screen always show. Null past the end.
 */
export function nextStep(
  steps: readonly WalkStep[],
  current: WalkStep,
  stillOpen: (step: AskStep) => boolean,
): WalkStep | null {
  const at = steps.indexOf(current);
  for (const step of steps.slice(at + 1))
    if (!isAsk(step) || stillOpen(step)) return step;
  return null;
}

/**
 * Where a walk starts: a walk the app closed in the middle of (its screen kept
 * on this phone) skips the welcome and starts at the first screen still open;
 * a new one starts at the top.
 */
export function resumeAt(
  steps: readonly WalkStep[],
  saved: string | null,
  stillOpen: (step: AskStep) => boolean,
): WalkStep | null {
  const resuming = saved !== null && saved !== "";
  for (const step of steps) {
    if (step === "welcome" && resuming) continue;
    if (!isAsk(step) || stillOpen(step)) return step;
  }
  return null;
}

/** The screen a walk was on, kept on this phone so closing the app resumes. */
export const WALK_STEP_KEY = "sales-xray:setup-walk-step";
/** The welcome was shown on this phone. */
export const WALK_WELCOMED_KEY = "sales-xray:setup-walk-welcomed";
/** "I don't make calls on this phone", per install. */
export const noCallsKey = (device: string) =>
  `sales-xray:setup-walk-no-calls:${device}`;
/** The test call was skipped on this install. */
export const testSkippedKey = (device: string) =>
  `sales-xray:setup-walk-test-skipped:${device}`;

export function readKey(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeKey(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage off: the walk asks once more next time.
  }
}

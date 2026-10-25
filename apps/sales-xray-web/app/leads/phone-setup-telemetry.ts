/**
 * Phone setup for the weekly friction report (owner, 25 Oct 2026: "where they
 * get stuck ... permission prompts"): each permission or settings screen the
 * flow asks for and what came of it (sx.permission_prompt), by the names the
 * phone's own snapshot uses, read from the phone's setup status before and
 * after. Never anything about calls, contacts or recordings themselves.
 */
import {
  track,
  type FlowStep as TelemetryStep,
  type PromptPermission,
} from "../telemetry";
import type { SetupStatus } from "./native-phone";
import {
  allFiles,
  blocked,
  done,
  folderPick,
  type FlowStep,
} from "./phone-setup-steps";

/** The flow's step as the friction report names it. */
export const telemetryStep = (step: FlowStep): TelemetryStep =>
  step === "callLog" ? "call_log" : step;

/** What the step asks Android for, as the permission snapshot names it. */
export function promptOf(
  step: FlowStep,
  status: SetupStatus,
): PromptPermission {
  if (step === "recordings")
    return allFiles(status)
      ? "all_files"
      : folderPick(status)
        ? "folder"
        : "rec_files";
  return step === "callLog" ? "call_log" : step;
}

export type PromptOutcome =
  | "granted"
  | "denied"
  | "blocked"
  | "not_opened"
  | "unknown";

/**
 * Granted when the phone now says it is done; not opened when a settings
 * screen didn't open; blocked when Android no longer asks (only the app's
 * settings can allow it); otherwise denied. Unknown without an answer.
 */
export function promptOutcome(
  step: FlowStep,
  after: SetupStatus | null,
  opened: unknown,
  settings: boolean,
): PromptOutcome {
  if (!after) return "unknown";
  if (done(after, step)) return "granted";
  if (settings && opened === false) return "not_opened";
  if (blocked(step, after)) return "blocked";
  return "denied";
}

/** An ask in progress: the step, the status before it, how it asks, when it began. */
export type Ask = {
  step: FlowStep;
  before: SetupStatus;
  /** It opens one of Android's settings screens, not a prompt. */
  settings: boolean;
  at: number;
  /** What the ask answered (a granted flag, or whether a screen opened). */
  opened: unknown;
};

/** An ask starting now. */
export function startAsk(
  step: FlowStep,
  before: SetupStatus,
  settings: boolean,
): Ask {
  return { step, before, settings, at: performance.now(), opened: null };
}

/** One ask in phone setup: what was asked, how, what came of it, how long. */
export function trackPrompt(ask: {
  step: FlowStep;
  before: SetupStatus;
  after: SetupStatus | null;
  opened: unknown;
  /** It opened one of Android's settings screens, not a prompt. */
  settings: boolean;
  /** One Fix from Settings rather than the whole setup. */
  fix: boolean;
  ms: number;
}) {
  try {
    track("sx.permission_prompt", {
      permission: promptOf(ask.step, ask.before),
      outcome: promptOutcome(ask.step, ask.after, ask.opened, ask.settings),
      via: ask.settings ? "settings" : "prompt",
      from: ask.fix ? "fix" : "setup",
      ms: Math.max(0, Math.min(600_000, Math.round(ask.ms))),
    });
  } catch {
    // Telemetry never breaks setup.
  }
}

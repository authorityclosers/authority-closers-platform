/**
 * What "Set up this phone" still has to ask, from the phone's setup status:
 * its own module, so first-run onboarding can decide without loading the
 * flow's screens (cold start, 24 Oct 2026). phone-setup-flow.tsx re-exports it.
 */
import type { CallRecorderStatus, SetupStatus } from "./native-phone";

export type FlowStep =
  | "calls"
  | "notifications"
  | "recordings"
  | "battery"
  | "autostart"
  | "callLog"
  | "recorder";

export const done = (status: SetupStatus, key: string) =>
  status.checks[key] === true;

/** MIUI and HyperOS show their recordings only with All files access (download builds). */
export const allFiles = (status: SetupStatus) =>
  status.needsAllFiles && status.allFilesSupported;

/** The Play build picks the recordings folder instead (S8). */
export const folderPick = (status: SetupStatus) =>
  status.needsAllFiles &&
  !status.allFilesSupported &&
  status.folderPickSupported;

/** A permission Android no longer asks for: only the app's settings allow it now. */
export const blocked = (step: FlowStep, status: SetupStatus) =>
  (step === "calls" && status.blocked.calls) ||
  (step === "notifications" && status.blocked.notifications) ||
  (step === "recordings" &&
    !allFiles(status) &&
    !folderPick(status) &&
    status.blocked.recordings);

/** What this phone still needs, in the order the flow asks. */
export function flowSteps(
  status: SetupStatus,
  recorder: CallRecorderStatus | null,
): FlowStep[] {
  const steps: FlowStep[] = [];
  if (!done(status, "calls")) steps.push("calls");
  if (!done(status, "notifications")) steps.push("notifications");
  if (!done(status, "recordings")) steps.push("recordings");
  if (!done(status, "battery")) steps.push("battery");
  if (status.autostartNeeded && !done(status, "autostart"))
    steps.push("autostart");
  if (status.callLogSupported && !done(status, "callLog"))
    steps.push("callLog");
  const dialerOff =
    status.recorder?.kind === "folder" && status.recorder.recording !== "on";
  if (
    (recorder?.available && !recorder.enabled) ||
    (!recorder?.available && dialerOff && !done(status, "recorder"))
  )
    steps.push("recorder");
  return steps;
}

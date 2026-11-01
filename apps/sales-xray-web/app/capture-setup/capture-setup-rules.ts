/**
 * Who goes through call capture setup, where, and which steps (owner, 30 Oct
 * 2026: "simple clicks and disclosure one by one, so that all our old as well as
 * new users have to agree"). Pure, so the gate decides without loading the flow.
 *
 * - An organisation's sellers must, on Home, Leads and Calls: until their name
 *   and phone are in, they agreed, and (in the phone app) this phone finished;
 *   or until they said no, which is asked again the next day.
 * - The phone app shows all five steps; the web shows the first two, then "open
 *   the app on your phone". An app too old to upload calls by itself is treated
 *   as the web, with "update the app".
 * - A personal workspace can't upload calls by itself, so it gets the same flow
 *   once in the phone app, every step skippable, without consent or uploads.
 * - Every phone is new: a fresh install has a new id and goes through it again.
 */

import { callIdFromPath } from "../analysis-routes";
import type { AutoCaptureStatus, SetupStatus } from "../leads/native-phone";
import type {
  CaptureFinishedPhone,
  CaptureSetup,
} from "./capture-setup-client";

/**
 * On the page while the setup is deciding or open, so "Set up this phone"
 * waits its turn (one flow, one screen at a time).
 */
export const CAPTURE_SETUP_ATTRIBUTE = "data-sx-capture-setup";

export type CaptureStep =
  | "profile"
  | "consent"
  | "recordings"
  | "background"
  | "uploads"
  /** The web's last step, or an app too old: finish on the phone. */
  | "phone"
  | "done";

/** What the phone app says about this phone, for the steps. */
export type PhoneFacts = Readonly<{
  device: string;
  model: string;
  family: string;
  version: string;
  /** This build can pick the folder and upload calls by itself. */
  captureSupported: boolean;
  folderPicked: boolean;
  /** The Phone app saves recordings, but its switch is off. */
  recorderOff: boolean;
  /** Google's Phone app: its recordings stay inside it. */
  privateDialler: boolean;
  battery: boolean;
  autostartNeeded: boolean;
  autostart: boolean;
  notifications: boolean;
  notificationsBlocked: boolean;
  uploadsOn: boolean;
  wifiOnly: boolean;
  /** Newest readable recording, when the phone says. */
  newestMs: number | null;
  /** That recording's length, when the phone says (newer apps). */
  newestDurationMs: number | null;
  /** A call placed from the app found its recording (the phone's own check). */
  testCall: boolean;
}>;

export function phoneFacts(
  setup: SetupStatus | null,
  capture: AutoCaptureStatus | null,
): PhoneFacts | null {
  if (!setup) return null;
  const recorder = setup.recorder;
  return {
    device: setup.device,
    model: setup.model,
    family: setup.family,
    version: setup.version,
    captureSupported:
      capture?.supported === true && setup.folderPickSupported === true,
    folderPicked: setup.folderPicked,
    recorderOff:
      recorder?.kind === "folder" &&
      recorder.recording === "off" &&
      setup.checks.recorder !== true,
    privateDialler: recorder?.kind === "private",
    battery: setup.checks.battery === true,
    autostartNeeded: setup.autostartNeeded,
    autostart: setup.checks.autostart === true,
    notifications: setup.checks.notifications === true,
    notificationsBlocked: setup.blocked.notifications,
    uploadsOn: capture?.on === true,
    wifiOnly: capture?.wifiOnly !== false,
    newestMs: recorder?.newestMs ?? null,
    newestDurationMs: recorder?.newestDurationMs ?? null,
    testCall: setup.checks.testCall === true,
  };
}

const TEST_CALL_KEY = (device: string) => `sx-test-call:${device}`;

/** The setup's own test call found its recording on this install. */
export function markTestCall(device: string) {
  try {
    window.localStorage.setItem(
      TEST_CALL_KEY(device),
      new Date().toISOString(),
    );
  } catch {
    // Private storage off: the next run asks for the test again.
  }
}

/**
 * Recording works on this phone: a call placed from the app found its
 * recording, the setup's test call did, or the chosen folder already holds a
 * call recording. Until then the setup ends its recording list with a
 * 10-second test call (competitor teardown #6, 1 Nov 2026).
 */
export function recordingProven(phone: PhoneFacts): boolean {
  if (phone.testCall || phone.newestMs !== null) return true;
  try {
    return window.localStorage.getItem(TEST_CALL_KEY(phone.device)) !== null;
  } catch {
    return false;
  }
}

/** Nothing on this phone stops a call's recording reaching Sales X-Ray now. */
export function recordingsLive(phone: PhoneFacts): boolean {
  return phone.folderPicked && !phone.privateDialler && !phone.recorderOff;
}

/**
 * Recordings work: nothing stops them, and one was found (orchestrator, 1 Nov
 * 2026: a phone finished with no folder counted as done for good, and its
 * seller sent no recording in a week). A run finishes only with this.
 */
export function recordingsReady(phone: PhoneFacts): boolean {
  return recordingsLive(phone) && recordingProven(phone);
}

const RECORDINGS_LATER = (device: string) => `sx-recordings-later:${device}`;
const LATER_MS = 24 * 60 * 60 * 1000;

/** The seller chose Not now at the end with recordings not working: asked again a day later. */
export function markRecordingsLater(device: string, now = Date.now()) {
  try {
    window.localStorage.setItem(
      RECORDINGS_LATER(device),
      new Date(now).toISOString(),
    );
  } catch {
    // Private storage off: it asks again at the next open.
  }
}

export function recordingsLater(device: string, now: number): boolean {
  try {
    const at = Date.parse(
      window.localStorage.getItem(RECORDINGS_LATER(device)) ?? "",
    );
    return Number.isFinite(at) && now >= at && now < at + LATER_MS;
  } catch {
    return false;
  }
}

const ORDER: CaptureStep[] = [
  "profile",
  "consent",
  "recordings",
  "background",
  "uploads",
  "phone",
  "done",
];
const PHONE_STEPS = new Set<CaptureStep>([
  "recordings",
  "background",
  "uploads",
]);

/**
 * The step a fix opens (Fix on the no-recording line of Calls and Reports,
 * competitor teardown #13, 1 Nov 2026): what fails on this phone, the
 * recording check first; on the web, "open the app on your phone".
 */
export function failingStep(phone: PhoneFacts | null): CaptureStep {
  if (!phone?.captureSupported) return "phone";
  if (
    phone.privateDialler ||
    !phone.folderPicked ||
    phone.recorderOff ||
    !recordingProven(phone)
  )
    return "recordings";
  if (!phone.battery || (phone.autostartNeeded && !phone.autostart))
    return "background";
  if (!phone.uploadsOn || !phone.notifications) return "uploads";
  // Everything looks on, yet calls have no recording: the check and its test call.
  return "recordings";
}

/** The steps, with the phone step a fix asked for in its place, even when this phone looks set. */
export function stepsWith(
  steps: CaptureStep[],
  asked?: CaptureStep,
): CaptureStep[] {
  if (
    !asked ||
    !PHONE_STEPS.has(asked) ||
    steps.includes(asked) ||
    !steps.includes("done")
  )
    return steps;
  const at = steps.findIndex(
    (step) => ORDER.indexOf(step) > ORDER.indexOf(asked),
  );
  return [...steps.slice(0, at), asked, ...steps.slice(at)];
}

const GATED = new Set([
  "/",
  "/dashboard",
  "/leads",
  "/leads/notes",
  "/calls",
  "/analysis",
  "/analysis/new",
  "/analysis/calls",
]);

/** Home, Leads and Calls (and their pages): where the setup is required. */
export function isGatedRoute(pathname: string | null): boolean {
  if (!pathname) return false;
  const route = pathname.replace(/\/$/, "") || "/";
  return (
    GATED.has(route) ||
    route.startsWith("/prospects/") ||
    route.startsWith("/leads/") ||
    callIdFromPath(route) !== null
  );
}

/** The seller said no (or turned it off) less than a day ago. */
export function noStillStands(setup: CaptureSetup, now: number): boolean {
  const again = setup.ask_again_at ? Date.parse(setup.ask_again_at) : NaN;
  return Number.isFinite(again) && now < again;
}

/** This install's newest finish in this workspace, whatever it found. */
function finishHere(setup: CaptureSetup, phone: PhoneFacts | null) {
  return phone?.device
    ? setup.phones.find((item) => item.device === phone.device)
    : undefined;
}

/** This phone finished before in this workspace with its recordings working. */
export function phoneFinished(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): boolean {
  return finishHere(setup, phone)?.recordings === true;
}

/** This phone went through the setup here before, even without recordings. */
export function phoneTried(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): boolean {
  return finishHere(setup, phone) !== undefined;
}

/**
 * This phone's own steps (recordings folder, background, uploads) are done: this
 * person finished setup on this install, with its recordings working, here or in
 * any other workspace (the server lists only those). A workspace switch asks only
 * for that workspace's consent (persona QA ph2-15, 1 Nov 2026: switching ran all
 * five steps again, and after every restart).
 */
export function phoneDone(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): boolean {
  return Boolean(
    phone?.device &&
      (phoneFinished(setup, phone) ||
        (setup.finished_devices ?? []).includes(phone.device)),
  );
}

/** Finished on this install in another workspace, not yet in this one. */
export function phoneDoneElsewhere(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): boolean {
  return phoneDone(setup, phone) && !phoneFinished(setup, phone);
}

/**
 * What a finished phone records for Team: never a number, only what is on.
 * Recordings count only when they work (recordingsReady); `proven` is for a
 * phone that already proved them in another workspace.
 */
export function finishedPhone(
  phone: PhoneFacts,
  proven = recordingProven(phone),
): CaptureFinishedPhone {
  return {
    device: phone.device,
    model: phone.model,
    family: phone.family,
    app_version: phone.version,
    recordings: recordingsLive(phone) && proven,
    background: phone.battery && (!phone.autostartNeeded || phone.autostart),
    uploads: phone.uploadsOn,
  };
}

/** Everything this phone's own steps check is on now (none of them would show). */
export function phoneReady(setup: CaptureSetup, phone: PhoneFacts): boolean {
  return !stepsFor(setup, phone).some((step) => PHONE_STEPS.has(step));
}

/** Whether an organisation's seller must go through it before Home, Leads and Calls. */
export function setupRequired(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
  now: number,
): boolean {
  if (!setup.required || setup.workspace !== "organisation") return false;
  if (noStillStands(setup, now)) return false;
  if (!setup.profile_complete || setup.consent !== "on") return true;
  // The web, or an app too old to upload calls by itself: the first two steps are all.
  if (!phone?.captureSupported) return false;
  // Finished with its recordings working, here or in another workspace (the gate
  // records the phone for this workspace's Team by itself): asked again only
  // when they stop (no folder, a private Phone app, the recorder off).
  if (phoneDone(setup, phone) && recordingsLive(phone)) return false;
  // Went through it before without recordings, and they work now (a call's
  // recording was found): nothing to show; the gate records it.
  if (phoneTried(setup, phone) && phoneReady(setup, phone)) return false;
  // A finish without recordings is never done (orchestrator, 1 Nov 2026): the
  // recordings step opens again at the next open, a day after a Not now.
  return !recordingsLater(phone.device, now);
}

/** The steps, in order, for this workspace and this place. */
export function stepsFor(
  setup: CaptureSetup,
  phone: PhoneFacts | null,
): CaptureStep[] {
  const personal = setup.workspace === "personal";
  const steps: CaptureStep[] = [];
  if (!setup.profile_complete) steps.push("profile");
  // Shown to everyone, even someone who agreed before: "all our old as well as
  // new users have to agree" (the agreed see their date and go on).
  steps.push("consent");
  if (!phone?.captureSupported) {
    if (!personal) steps.push("phone");
    return steps;
  }
  // The phone's own steps, once per install for this person (ph2-15); a run
  // again from Settings in a workspace it finished in still shows them, and so
  // does a phone whose recordings stopped since.
  if (phoneDoneElsewhere(setup, phone) && recordingsLive(phone)) {
    steps.push("done");
    return steps;
  }
  if (
    !phone.folderPicked ||
    phone.recorderOff ||
    phone.privateDialler ||
    !recordingProven(phone)
  )
    steps.push("recordings");
  if (!phone.battery || (phone.autostartNeeded && !phone.autostart))
    steps.push("background");
  if (!personal && (!phone.uploadsOn || !phone.notifications))
    steps.push("uploads");
  steps.push("done");
  return steps;
}

const PERSONAL_SEEN = (person: string, tenant: string) =>
  `sx-capture-setup:${person}:${tenant}`;

/** A personal workspace's flow shows once per phone. */
export function personalSeen(person: string, tenant: string): boolean {
  try {
    return window.localStorage.getItem(PERSONAL_SEEN(person, tenant)) !== null;
  } catch {
    // Without storage it is never offered: it is optional here.
    return true;
  }
}

export function markPersonalSeen(person: string, tenant: string) {
  try {
    window.localStorage.setItem(
      PERSONAL_SEEN(person, tenant),
      new Date().toISOString(),
    );
  } catch {
    // Nothing kept: it may show once more; it can be skipped.
  }
}

/** "a minute ago", "3 hours ago", "on 28 Oct": when the newest recording was saved. */
export function savedWhen(newestMs: number | null, now: number): string | null {
  if (!newestMs || newestMs > now) return null;
  const minutes = Math.floor((now - newestMs) / 60_000);
  if (minutes < 1) return "less than a minute ago";
  if (minutes < 60)
    return minutes === 1 ? "a minute ago" : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  return `on ${new Date(newestMs).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "Asia/Kolkata",
  })}`;
}
